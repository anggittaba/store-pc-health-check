"""Command line.

    python -m pchealth backfill [--days 30] [--end YYYY-MM-DD]   fresh 30-day synthetic history + daily runs
    python -m pchealth today [--date YYYY-MM-DD]                 add the missing day(s) up to today and run them
    python -m pchealth run --date YYYY-MM-DD                     (re)run one day; idempotent
    python -m pchealth evaluate [--out docs/results]             precision / recall vs injected faults
    python -m pchealth export --date D --format csv|xlsx --out F
    python -m pchealth resume [--date D]                         print the recap text
    python -m pchealth serve [--port 8000]
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from . import data, db, engine, evaluate, export, llm, rules, settings


def _open():
    con = db.connect(settings.db_path())
    cfg = rules.load_rules(settings.rules_path())
    return con, cfg


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="pchealth")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("backfill")
    b.add_argument("--days", type=int, default=30)
    b.add_argument("--end", default=None)
    t = sub.add_parser("today")
    t.add_argument("--date", default=None)
    r = sub.add_parser("run")
    r.add_argument("--date", required=True)
    e = sub.add_parser("evaluate")
    e.add_argument("--out", default=None)
    e.add_argument("--seeds", type=int, default=0, help="also score N independent simulated fleets")
    x = sub.add_parser("export")
    x.add_argument("--date", default=None)
    x.add_argument("--format", choices=["csv", "xlsx"], default="csv")
    x.add_argument("--out", required=True)
    rs = sub.add_parser("resume")
    rs.add_argument("--date", default=None)
    s = sub.add_parser("serve")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8000)
    a = ap.parse_args(argv)

    if a.cmd == "serve":
        import uvicorn
        from .web import create_app
        uvicorn.run(create_app(), host=a.host, port=a.port, log_level="warning")
        return 0

    con, cfg = _open()
    provider = llm.provider_from_env()
    if a.cmd == "backfill":
        end = date.fromisoformat(a.end) if a.end else date.today()
        days = data.backfill(con, end, a.days)
        results = engine.run_all(con, cfg, trigger="backfill", provider=provider)
        last = results[-1]
        print(f"generated {len(days)} days ({days[0]} to {days[-1]}); ran {len(results)} daily checks")
        print(f"{last.run_date}: {last.stats['stores_flagged']} stores flagged, {last.stats['issues']} issues, "
              f"{last.stats['stores_missing']} {'store' if last.stats['stores_missing'] == 1 else 'stores'} without data · writer: {last.writer}")
    elif a.cmd == "today":
        end = date.fromisoformat(a.date) if a.date else date.today()
        added = data.generate_until(con, end)
        res = engine.run_day(con, cfg, end.isoformat(), trigger="scheduled", provider=provider)
        print(f"added pulls for: {', '.join(added) or 'nothing new'}")
        print(f"{res.run_date}: {res.stats['stores_flagged']} stores flagged, {res.stats['issues']} issues "
              f"({res.stats['new']} new, {res.stats['resolved']} cleared), {res.stats["stores_missing"]} {"store" if res.stats["stores_missing"] == 1 else "stores"} without data"
              f"{' · replaced an earlier run of this day' if res.replaced else ''} · writer: {res.writer}")
    elif a.cmd == "run":
        res = engine.run_day(con, cfg, a.date, trigger="manual", provider=provider)
        print(json.dumps({"date": res.run_date, **res.stats, "replaced": res.replaced, "writer": res.writer}))
    elif a.cmd == "evaluate":
        res = evaluate.score(con)
        labels = {t: cfg[t]["label"] for t in rules.ISSUE_ORDER}
        md = evaluate.markdown(res, labels)
        confirm = evaluate.score_min_streak(con, 2)
        md += "\n\nWait-and-confirm variant (only issues seen 2+ checks in a row):\n\n| Issue type | Precision | Recall |\n|---|---:|---:|\n"
        md += "\n".join(f"| {labels[t]} | {evaluate.pct(v['precision'])} | {evaluate.pct(v['recall'])} |" for t, v in confirm.items())
        res["confirm_2_days"] = confirm
        if a.seeds:
            last = date.fromisoformat(res["to"])
            multi = evaluate.multi_seed(cfg, last, res["days"], range(1, a.seeds + 1))
            md += "\n\n" + evaluate.multi_markdown(multi, labels)
            res["multi_seed"] = multi
        print(md)
        if a.out:
            out = Path(a.out)
            out.mkdir(parents=True, exist_ok=True)
            (out / "evaluation.json").write_text(json.dumps(res, indent=2))
            (out / "evaluation.md").write_text(md + "\n")
    elif a.cmd == "export":
        day = a.date or db.dates(con)[-1]
        if a.format == "csv":
            Path(a.out).write_text(export.to_csv(con, cfg, day))
        else:
            Path(a.out).write_bytes(export.to_xlsx(con, cfg, day))
        print(a.out)
    elif a.cmd == "resume":
        day = a.date or db.dates(con)[-1]
        r = con.execute("SELECT text FROM resumes WHERE date=?", (day,)).fetchone()
        print(r["text"] if r else f"no run for {day}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
