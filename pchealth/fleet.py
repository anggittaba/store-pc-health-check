"""Fleet roll-ups for the monitoring screens: per-store and per-PC status, KPI deltas and 30-day fleet trends.

Read-only views over the rule results. Nothing here decides what counts as an issue or how severe it is;
it only buckets what the rule engine already wrote to the issues table.
"""

from __future__ import annotations

from collections import Counter, defaultdict

from .rules import ISSUE_ORDER, RANK

# Status buckets shown on tiles and KPI cards. "critical" = worst issue high or critical (red),
# "warning" = worst issue medium or low (amber), "nodata" = the store sent no pull (grey).
STATUSES = ["critical", "warning", "nodata", "healthy"]
STATUS_LABEL = {"critical": "Critical", "warning": "Warning", "nodata": "No data", "healthy": "Healthy"}

# Short tag per issue type for the compact store tiles.
TAG = {"missing_pull": "NO DATA", "edc_offline": "EDC", "lan_degraded": "LAN", "overheating": "TEMP",
       "disk_smart": "SMART", "disk_space": "DISK", "ups_problem": "UPS", "ram_below_spec": "RAM",
       "no_reboot": "UPTIME", "windows_activation": "LICENSE"}


def severity_status(severity: str | None) -> str:
    if severity is None:
        return "healthy"
    return "critical" if RANK[severity] >= RANK["high"] else "warning"


def store_status(items: list[dict]) -> str:
    """Status of one store from its issues for the day (any order)."""
    if not items:
        return "healthy"
    if any(i["issue_type"] == "missing_pull" for i in items):
        return "nodata"
    return severity_status(max((i["severity"] for i in items), key=lambda s: RANK[s]))


def pc_status_counts(con, day: str) -> Counter:
    """How many PCs are healthy / warning / critical / sent no data on a day."""
    pcs = [r["pc_id"] for r in con.execute("SELECT pc_id FROM pcs")]
    reported = {r[0] for r in con.execute("SELECT pc_id FROM snapshots WHERE date=?", (day,))}
    worst: dict[str, str] = {}
    for r in con.execute("SELECT pc_id, severity FROM issues WHERE date=? AND pc_id IS NOT NULL AND pc_id != ''", (day,)):
        if r["pc_id"] not in worst or RANK[r["severity"]] > RANK[worst[r["pc_id"]]]:
            worst[r["pc_id"]] = r["severity"]
    out = Counter({s: 0 for s in STATUSES})
    for p in pcs:
        out["nodata" if p not in reported else severity_status(worst.get(p))] += 1
    return out


def store_status_counts(con, day: str) -> Counter:
    by = defaultdict(list)
    for r in con.execute("SELECT store_code, issue_type, severity FROM issues WHERE date=?", (day,)):
        by[r["store_code"]].append(dict(r))
    out = Counter({s: 0 for s in STATUSES})
    for (code,) in con.execute("SELECT code FROM stores"):
        out[store_status(by.get(code, []))] += 1
    return out


def kpis(con, day: str, prev_day: str | None) -> list[dict]:
    """The four KPI tiles: healthy, warning and critical PCs, plus stores with no data, each with the change since yesterday."""
    now = pc_status_counts(con, day)
    before = pc_status_counts(con, prev_day) if prev_day else None
    s_now = store_status_counts(con, day)
    s_before = store_status_counts(con, prev_day) if prev_day else None
    total = sum(now.values())
    rows = [("healthy", "Healthy PCs", now["healthy"], before["healthy"] if before else None, f"of {total} PCs"),
            ("warning", "Warning PCs", now["warning"], before["warning"] if before else None, "worst issue medium or low"),
            ("critical", "Critical PCs", now["critical"], before["critical"] if before else None, "worst issue high or critical"),
            ("nodata", "Stores with no data", s_now["nodata"], s_before["nodata"] if s_before else None, "no pull from any PC")]
    out = []
    for key, label, n, b, note in rows:
        out.append({"key": key, "label": label, "value": n, "delta": None if b is None else n - b, "note": note,
                    # rising healthy is good; rising anything else is bad
                    "good": None if b is None or n == b else ((n > b) == (key == "healthy"))})
    return out


def type_trend(con, days: list[str]) -> dict[str, list[int]]:
    """Issues per type per day over the window (for the stacked chart)."""
    idx = {d: k for k, d in enumerate(days)}
    out = {k: [0] * len(days) for k in ISSUE_ORDER}
    if not days:
        return out
    for r in con.execute("SELECT date, issue_type, COUNT(*) c FROM issues WHERE date BETWEEN ? AND ? GROUP BY 1, 2",
                         (days[0], days[-1])):
        if r["date"] in idx:
            out[r["issue_type"]][idx[r["date"]]] = r["c"]
    return out
