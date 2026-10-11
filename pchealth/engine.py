"""The daily run: rules over today's pulls, plus streaks, trends, new/resolved and a run log.

Running the same day twice replaces that day's result instead of adding to it (idempotent);
the run log keeps both runs so you can see it happened.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from . import db, resume, rules
from .rules import ISSUE_ORDER, RANK


@dataclass
class RunResult:
    run_date: str
    issues: list[dict]
    resolved: list[dict]
    missing_stores: list[str]
    replaced: bool
    writer: str
    stats: dict = field(default_factory=dict)


def _key(i) -> tuple:
    return (i["store_code"], i["pc_id"] or "", i["issue_type"])


def sort_key(i: dict):
    return (-RANK[i["severity"]], ISSUE_ORDER.index(i["issue_type"]), -i["streak"], i["store_code"], i["pc_id"] or "")


def run_day(con, cfg: dict, day: str, trigger: str = "manual", provider=None) -> RunResult:
    have = set(db.snapshot_dates(con))
    if day not in have:
        raise ValueError(f"no health pull stored for {day}; generate it first")
    prev_day = (date.fromisoformat(day) - timedelta(days=1)).isoformat()
    if prev_day in have and not con.execute("SELECT 1 FROM runs WHERE run_date=? AND status='ok'", (prev_day,)).fetchone():
        run_day(con, cfg, prev_day, trigger="catch-up", provider=provider)

    started = datetime.now().replace(microsecond=0).isoformat()
    replaced = con.execute("SELECT COUNT(*) FROM runs WHERE run_date=? AND status='ok'", (day,)).fetchone()[0] > 0
    stores = {r["code"]: dict(r) for r in con.execute("SELECT * FROM stores")}
    expected = con.execute("SELECT COUNT(*) FROM pcs").fetchone()[0]
    snaps = [dict(r) for r in con.execute("SELECT * FROM snapshots WHERE date=? ORDER BY pc_id", (day,))]
    reported = {s["store_code"] for s in snaps}
    missing = sorted(set(stores) - reported)

    prev = defaultdict(dict)  # yesterday's issues by key
    if prev_day in have:
        for r in con.execute("SELECT * FROM issues WHERE date=?", (prev_day,)):
            prev[_key(r)] = dict(r)
    prev_missing = {k[0] for k in prev if k[2] == "missing_pull"}

    # for stores that were missing yesterday, compare with the last day they did report
    def previous_for(store_code: str) -> dict:
        mine = {k: v for k, v in prev.items() if k[0] == store_code}
        if store_code not in prev_missing:
            return mine
        # missing yesterday: keep yesterday's missing-pull streak, and compare PC issues with the last day it reported
        row = con.execute("SELECT MAX(date) FROM snapshots WHERE store_code=? AND date<?", (store_code, day)).fetchone()
        if row[0]:
            for r in con.execute("SELECT * FROM issues WHERE date=? AND store_code=?", (row[0], store_code)):
                if r["issue_type"] != "missing_pull":
                    mine[_key(r)] = dict(r)
        return mine

    history = defaultdict(list)  # pc_id -> last N snapshot rows (oldest first), for trends
    n = cfg["general"]["trend_window_days"]
    since = (date.fromisoformat(day) - timedelta(days=n + 3)).isoformat()
    for r in con.execute("SELECT * FROM snapshots WHERE date>? AND date<=? ORDER BY date", (since, day)):
        history[r["pc_id"]].append(dict(r))

    rec_after = cfg["general"]["recurring_after_days"]
    no_esc = set(cfg["general"]["no_escalation"])
    issues: list[dict] = []

    def add(store_code, pc_id, f: rules.Finding, before: dict):
        old = before.get((store_code, pc_id or "", f.issue_type))
        streak = old["streak"] + 1 if old else 1
        sev = f.severity
        if streak >= rec_after and f.issue_type not in no_esc:
            sev = rules.bump(sev)
        tr = None
        if pc_id and f.issue_type in rules.TREND_FIELD:
            vals = [h[rules.TREND_FIELD[f.issue_type]] for h in history[pc_id][-n:]]
            tr = rules.trend(vals, f.issue_type, cfg)
        issues.append({"date": day, "store_code": store_code, "pc_id": pc_id, "issue_type": f.issue_type,
                       "severity": sev, "base_severity": f.severity, "value": f.value, "threshold": f.threshold,
                       "reason": f.reason, "streak": streak, "trend": tr, "is_new": int(old is None)})

    before_by_store = {code: previous_for(code) for code in stores}
    for code in missing:
        mp = cfg["missing_pull"]
        add(code, None, rules.Finding("missing_pull", mp["missing_severity"], "no pull", "pull by 06:00",
                                      "no health data arrived from any PC in this store"), before_by_store[code])
    for s in snaps:
        for f in rules.check_pc(s, cfg):
            add(s["store_code"], s["pc_id"], f, before_by_store[s["store_code"]])
    issues.sort(key=sort_key)

    today_keys = {_key(i) for i in issues}
    resolved = []
    for code in stores:
        if code in missing:
            continue  # no data today: we can't say anything was fixed
        for k, old in before_by_store[code].items():
            if k not in today_keys:
                resolved.append({"date": day, "store_code": code, "pc_id": old["pc_id"],
                                 "issue_type": old["issue_type"], "open_days": old["streak"]})
    resolved.sort(key=lambda r: (ISSUE_ORDER.index(r["issue_type"]), r["store_code"]))

    con.execute("DELETE FROM issues WHERE date=?", (day,))
    con.execute("DELETE FROM resolved WHERE date=?", (day,))
    cols = ["date", "store_code", "pc_id", "issue_type", "severity", "base_severity", "value", "threshold", "reason",
            "streak", "trend", "is_new"]
    con.executemany(f"INSERT INTO issues ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                    [[i[c] for c in cols] for i in issues])
    con.executemany("INSERT INTO resolved VALUES (?,?,?,?,?)",
                    [(r["date"], r["store_code"], r["pc_id"], r["issue_type"], r["open_days"]) for r in resolved])

    stats = {
        "pcs_expected": expected, "pcs_reported": len(snaps), "stores_missing": len(missing),
        "issues": len(issues), "stores_flagged": len({i["store_code"] for i in issues}),
        "new": sum(i["is_new"] for i in issues), "resolved": len(resolved),
    }
    text, explanations, writer = resume.write(con, cfg, day, issues, resolved, stores, provider)
    con.execute("INSERT OR REPLACE INTO resumes VALUES (?,?,?,?)", (day, writer, text, json.dumps(explanations)))
    con.execute(
        "INSERT INTO runs (run_date, started_at, finished_at, trigger, pcs_expected, pcs_reported, stores_missing, "
        "issues, stores_flagged, new, resolved, writer, replaced, status) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?, 'ok')",
        (day, started, datetime.now().replace(microsecond=0).isoformat(), trigger, stats["pcs_expected"],
         stats["pcs_reported"], stats["stores_missing"], stats["issues"], stats["stores_flagged"], stats["new"],
         stats["resolved"], writer, int(replaced)))
    con.commit()
    return RunResult(day, issues, resolved, missing, replaced, writer, stats)


def run_all(con, cfg: dict, trigger: str = "backfill", provider=None) -> list[RunResult]:
    out = []
    for d in db.snapshot_dates(con):
        out.append(run_day(con, cfg, d, trigger=trigger, provider=provider))
    return out
