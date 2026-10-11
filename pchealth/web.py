"""Dashboard: server-rendered pages over the daily run results. No JavaScript framework, charts are inline SVG."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import charts, db, export, resume, rules, settings
from .rules import ISSUE_ORDER, RANK, SEVERITIES

HERE = Path(__file__).parent
OWNERS = ["Store staff", "Remote IT", "Vendor"]


def create_app(con=None, cfg=None) -> FastAPI:
    con = con or db.connect(settings.db_path())
    cfg = cfg or rules.load_rules(settings.rules_path())
    app = FastAPI(title="Store PC Health Check", docs_url=None, redoc_url=None)
    app.mount("/static", StaticFiles(directory=str(HERE / "static")), name="static")
    t = Jinja2Templates(directory=str(HERE / "templates"))
    labels = {k: cfg[k]["label"] for k in ISSUE_ORDER}
    t.env.globals.update(LABELS=labels, ISSUE_ORDER=ISSUE_ORDER, SEVERITIES=SEVERITIES, OWNERS=OWNERS,
                         PLAYBOOK=cfg["playbook"], nice_date=resume.nice_date, ordinal=resume.ordinal, low=resume.low)
    t.env.filters["hm"] = lambda v: (v or "")[11:16]

    def run_dates() -> list[str]:
        return db.dates(con)

    def pick_day(d: str | None) -> str:
        ds = run_dates()
        if not ds:
            raise HTTPException(503, "No daily run yet. Run `python -m pchealth backfill` first.")
        if d is None:
            return ds[-1]
        if d not in ds:
            raise HTTPException(404, f"No run for {d}")
        return d

    def ctx(request: Request, day: str, page: str, **kw) -> dict:
        ds = run_dates()
        i = ds.index(day)
        run = con.execute("SELECT * FROM runs WHERE run_date=? ORDER BY id DESC LIMIT 1", (day,)).fetchone()
        lo, hi = con.execute("SELECT MIN(pulled_at), MAX(pulled_at) FROM snapshots WHERE date=?", (day,)).fetchone()
        pull_window = f"{lo[11:16]}–{hi[11:16]}" if lo else None
        return {"n_days": len(ds), "pull_window": pull_window,"request": request, "day": day, "page": page, "edition": i + 1,
                "prev_day": ds[i - 1] if i > 0 else None, "next_day": ds[i + 1] if i + 1 < len(ds) else None,
                "latest": ds[-1], "run": dict(run) if run else None, **kw}

    def load(day: str):
        stores = {r["code"]: dict(r) for r in con.execute("SELECT * FROM stores ORDER BY code")}
        pcs = {r["pc_id"]: dict(r) for r in con.execute("SELECT * FROM pcs")}
        issues = [dict(r) for r in con.execute("SELECT * FROM issues WHERE date=?", (day,))]
        from .engine import sort_key
        issues.sort(key=sort_key)
        handled = defaultdict(list)
        for h in con.execute("SELECT * FROM handled WHERE date=? ORDER BY id", (day,)):
            handled[(h["store_code"], h["issue_type"])].append(dict(h))
        for i in issues:
            i["where"] = resume.where(i, pcs)
            i["pb"] = rules.playbook_for(cfg, i)
            i["owner"] = i["pb"]["owner"]
            i["handled"] = handled.get((i["store_code"], i["issue_type"]), [])
        return stores, pcs, issues

    def store_rows(stores, issues) -> list[dict]:
        by = defaultdict(list)
        for i in issues:
            by[i["store_code"]].append(i)
        out = []
        for code, items in by.items():
            out.append({"code": code, "name": stores[code]["name"], "area": stores[code]["area"], "items": items,
                        "worst": items[0]["severity"], "top": items[0],
                        "open": [i for i in items if not i["handled"]],
                        "owners": sorted({i["owner"] for i in items}, key=OWNERS.index),
                        "streak": max(i["streak"] for i in items), "new": any(i["is_new"] for i in items)})
        out.sort(key=lambda s: resume.store_rank(s["items"]))
        return out

    @app.get("/healthz")
    def healthz():
        return {"ok": True, "latest": (run_dates() or [None])[-1]}

    @app.get("/", response_class=HTMLResponse)
    def overview(request: Request, d: str | None = None):
        day = pick_day(d)
        stores, pcs, issues = load(day)
        rows = store_rows(stores, issues)
        sev = Counter(r["worst"] for r in rows)
        resolved = [dict(r) for r in con.execute("SELECT * FROM resolved WHERE date=?", (day,))]
        missing = [i for i in issues if i["issue_type"] == "missing_pull"]
        owners = Counter(i["owner"] for i in issues if not i["handled"])
        types = Counter(i["issue_type"] for i in issues)
        trend_days = [x for x in run_dates() if x <= day][-30:]
        daily = []
        for x in trend_days:
            r = con.execute("SELECT COUNT(DISTINCT store_code) FROM issues WHERE date=? AND severity IN ('high','critical')", (x,)).fetchone()[0]
            a = con.execute("SELECT COUNT(DISTINCT store_code) FROM issues WHERE date=?", (x,)).fetchone()[0]
            daily.append((x, a, r))
        urgent = [r for r in rows if RANK[r["worst"]] >= RANK["high"]]
        return t.TemplateResponse(request, "overview.html", ctx(
            request, day, "today", rows=rows, urgent=urgent, sev_count=sev, resolved=resolved, missing=missing,
            owners=owners, types=types, issues=issues, n_stores=len(stores),
            new=[i for i in issues if i["is_new"]],
            spark=charts.flagged_bars(daily, day), type_bars=charts.type_bars(types, labels)))

    @app.get("/stores", response_class=HTMLResponse)
    def stores_page(request: Request, d: str | None = None, type: str = "", severity: str = "", owner: str = "",
                    show: str = "open"):
        day = pick_day(d)
        stores, pcs, issues = load(day)
        sel = issues
        if type:
            sel = [i for i in sel if i["issue_type"] == type]
        if severity:
            sel = [i for i in sel if RANK[i["severity"]] >= RANK[severity]]
        if owner:
            sel = [i for i in sel if i["owner"] == owner]
        rows = store_rows(stores, sel)
        if show == "open":
            rows = [r for r in rows if r["open"]]
        healthy = len(stores) - len({i["store_code"] for i in issues})
        return t.TemplateResponse(request, "stores.html", ctx(
            request, day, "stores", rows=rows, f_type=type, f_sev=severity, f_owner=owner, show=show,
            healthy=healthy, total=len(stores), all_flagged=len({i["store_code"] for i in issues})))

    @app.get("/stores/{code}", response_class=HTMLResponse)
    def store_detail(request: Request, code: str, d: str | None = None):
        day = pick_day(d)
        stores, pcs, issues = load(day)
        if code not in stores:
            raise HTTPException(404, "Unknown store")
        mine = [i for i in issues if i["store_code"] == code]
        r = con.execute("SELECT explanations, writer FROM resumes WHERE date=?", (day,)).fetchone()
        explanation = json.loads(r["explanations"]).get(code) if r else None
        store_pcs = [p for p in pcs.values() if p["store_code"] == code]
        store_pcs.sort(key=lambda p: p["pc_id"])
        today = {s["pc_id"]: dict(s) for s in con.execute("SELECT * FROM snapshots WHERE date=? AND store_code=?", (day, code))}
        days = [x for x in db.snapshot_dates(con) if x <= day][-30:]
        hist = defaultdict(dict)
        for s in con.execute("SELECT * FROM snapshots WHERE store_code=? AND date BETWEEN ? AND ?", (code, days[0], day)):
            hist[s["pc_id"]][s["date"]] = dict(s)
        flagged = defaultdict(set)
        for s in con.execute("SELECT date, pc_id, issue_type FROM issues WHERE store_code=? AND date BETWEEN ? AND ?",
                             (code, days[0], day)):
            flagged[(s["pc_id"] or "", s["issue_type"])].add(s["date"])
        panels = charts.store_panels(store_pcs, hist, days, cfg, flagged)
        resolved = [dict(x) for x in con.execute("SELECT * FROM resolved WHERE date=? AND store_code=?", (day, code))]
        return t.TemplateResponse(request, "store.html", ctx(
            request, day, "stores", store=stores[code], issues=mine, explanation=explanation,
            writer=r["writer"] if r else "", pcs=store_pcs, today=today, panels=panels, resolved=resolved,
            history_from=days[0]))

    @app.post("/handled")
    def mark_handled(d: str = Form(...), store: str = Form(...), issue_type: str = Form(...), note: str = Form(""),
                     back: str = Form("/")):
        pick_day(d)
        if issue_type not in ISSUE_ORDER:
            raise HTTPException(400, "Unknown issue type")
        con.execute("INSERT INTO handled (date, store_code, issue_type, note, by, at) VALUES (?,?,?,?,?,?)",
                    (d, store, issue_type, note.strip()[:500], settings.operator(),
                     datetime.now().replace(microsecond=0).isoformat()))
        con.commit()
        return RedirectResponse(back if back.startswith("/") else "/", status_code=303)

    @app.post("/handled/{hid}/undo")
    def undo_handled(hid: int, back: str = Form("/")):
        con.execute("DELETE FROM handled WHERE id=?", (hid,))
        con.commit()
        return RedirectResponse(back if back.startswith("/") else "/", status_code=303)

    @app.get("/issues", response_class=HTMLResponse)
    def issue_types(request: Request, d: str | None = None):
        day = pick_day(d)
        stores, pcs, issues = load(day)
        days = [x for x in run_dates() if x <= day][-30:]
        counts = defaultdict(lambda: [0] * len(days))
        idx = {x: n for n, x in enumerate(days)}
        for r in con.execute("SELECT date, issue_type, COUNT(*) c FROM issues WHERE date BETWEEN ? AND ? GROUP BY 1,2",
                             (days[0], day)):
            counts[r["issue_type"]][idx[r["date"]]] = r["c"]
        resolved = Counter(r["issue_type"] for r in con.execute("SELECT issue_type FROM resolved WHERE date=?", (day,)))
        rows = []
        for k in ISSUE_ORDER:
            its = [i for i in issues if i["issue_type"] == k]
            rows.append({"type": k, "label": labels[k], "count": len(its),
                         "stores": len({i["store_code"] for i in its}),
                         "new": sum(i["is_new"] for i in its),
                         "recurring": sum(1 for i in its if i["streak"] >= cfg["general"]["recurring_after_days"]),
                         "worst": max((i["severity"] for i in its), key=lambda s: RANK[s], default=None),
                         "resolved": resolved[k],
                         "owner": ", ".join(sorted({i["owner"] for i in its}, key=OWNERS.index)) or cfg["playbook"][k]["owner"],
                         "spark": charts.sparkline(counts[k]), "total30": sum(counts[k])})
        rows.sort(key=lambda r: (-r["count"], ISSUE_ORDER.index(r["type"])))
        return t.TemplateResponse(request, "issues.html", ctx(request, day, "issues", rows=rows, n_days=len(days)))

    @app.get("/resume", response_class=HTMLResponse)
    def resume_page(request: Request, d: str | None = None):
        day = pick_day(d)
        stores, pcs, issues = load(day)
        r = con.execute("SELECT * FROM resumes WHERE date=?", (day,)).fetchone()
        expl = json.loads(r["explanations"]) if r else {}
        rows = store_rows(stores, issues)
        return t.TemplateResponse(request, "resume.html", ctx(
            request, day, "resume", text=r["text"] if r else "", writer=r["writer"] if r else "", rows=rows, expl=expl))

    @app.get("/runs", response_class=HTMLResponse)
    def runs_page(request: Request, d: str | None = None):
        day = pick_day(d)
        runs = [dict(r) for r in con.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 60")]
        return t.TemplateResponse(request, "runs.html", ctx(request, day, "runs", runs=runs))

    @app.get("/export.csv")
    def export_csv(d: str | None = None):
        day = pick_day(d)
        return Response(export.to_csv(con, cfg, day), media_type="text/csv",
                        headers={"Content-Disposition": f'attachment; filename="pc-health-recap-{day}.csv"'})

    @app.get("/export.xlsx")
    def export_xlsx(d: str | None = None):
        day = pick_day(d)
        return Response(export.to_xlsx(con, cfg, day),
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": f'attachment; filename="pc-health-recap-{day}.xlsx"'})

    @app.get("/resume.txt", response_class=PlainTextResponse)
    def resume_txt(d: str | None = None):
        day = pick_day(d)
        r = con.execute("SELECT text FROM resumes WHERE date=?", (day,)).fetchone()
        return r["text"] if r else ""

    return app
