"""Score the rules against the faults the simulator injected: precision and recall per issue type.

This measures the rules against their own simulator. It shows the rules catch what the
generator planted and how noise (one-off spikes) and slow onsets trip them up. It says
nothing about accuracy on a real fleet.
"""

from __future__ import annotations

from collections import Counter

from .rules import ISSUE_ORDER


def score(con) -> dict:
    days = [r[0] for r in con.execute("SELECT DISTINCT date FROM issues ORDER BY date")]
    if not days:
        return {"days": 0, "types": {}, "overall": {}}
    lo, hi = days[0], days[-1]
    truth = {(r["date"], r["store_code"], r["pc_id"] or "", r["issue_type"])
             for r in con.execute("SELECT * FROM ground_truth WHERE date BETWEEN ? AND ?", (lo, hi))}
    found = {(r["date"], r["store_code"], r["pc_id"] or "", r["issue_type"])
             for r in con.execute("SELECT * FROM issues WHERE date BETWEEN ? AND ?", (lo, hi))}
    missing_days = {(r["date"], r["store_code"]) for r in con.execute(
        "SELECT date, store_code FROM issues WHERE issue_type='missing_pull' AND date BETWEEN ? AND ?", (lo, hi))}
    tp, fp, fn, hidden = Counter(), Counter(), Counter(), Counter()
    for k in found:
        (tp if k in truth else fp)[k[3]] += 1
    for k in truth - found:
        fn[k[3]] += 1
        if (k[0], k[1]) in missing_days and k[3] != "missing_pull":
            hidden[k[3]] += 1
    types = {}
    for t in ISSUE_ORDER:
        p = tp[t] / (tp[t] + fp[t]) if tp[t] + fp[t] else None
        r = tp[t] / (tp[t] + fn[t]) if tp[t] + fn[t] else None
        types[t] = {"true_pos": tp[t], "false_pos": fp[t], "false_neg": fn[t], "hidden_by_missing_pull": hidden[t],
                    "precision": p, "recall": r}
    TP, FP, FN = sum(tp.values()), sum(fp.values()), sum(fn.values())
    return {"days": len(days), "from": lo, "to": hi, "types": types,
            "overall": {"true_pos": TP, "false_pos": FP, "false_neg": FN, "hidden_by_missing_pull": sum(hidden.values()),
                        "precision": TP / (TP + FP) if TP + FP else None, "recall": TP / (TP + FN) if TP + FN else None}}


def pct(v) -> str:
    return "n/a" if v is None else f"{v * 100:.1f}%"


def markdown(res: dict, labels: dict) -> str:
    out = [f"Scored over {res['days']} simulated days ({res.get('from')} to {res.get('to')}). "
           "Unit: one issue type on one PC on one day (store-level for missing pulls).", "",
           "| Issue type | Found & real | False alarms | Missed | of which hidden by a missing pull | Precision | Recall |",
           "|---|---:|---:|---:|---:|---:|---:|"]
    for t, v in res["types"].items():
        out.append(f"| {labels[t]} | {v['true_pos']} | {v['false_pos']} | {v['false_neg']} | {v['hidden_by_missing_pull']} | "
                   f"{pct(v['precision'])} | {pct(v['recall'])} |")
    o = res["overall"]
    out.append(f"| **All types** | **{o['true_pos']}** | **{o['false_pos']}** | **{o['false_neg']}** | "
               f"**{o['hidden_by_missing_pull']}** | **{pct(o['precision'])}** | **{pct(o['recall'])}** |")
    return "\n".join(out)


def score_min_streak(con, min_streak: int) -> dict:
    """Same score, but only counting issues seen on `min_streak`+ checks in a row (a 'wait and confirm' variant)."""
    days = [r[0] for r in con.execute("SELECT DISTINCT date FROM issues ORDER BY date")]
    lo, hi = days[0], days[-1]
    truth = {(r["date"], r["store_code"], r["pc_id"] or "", r["issue_type"])
             for r in con.execute("SELECT * FROM ground_truth WHERE date BETWEEN ? AND ?", (lo, hi))}
    found = {(r["date"], r["store_code"], r["pc_id"] or "", r["issue_type"])
             for r in con.execute("SELECT * FROM issues WHERE date BETWEEN ? AND ? AND streak >= ?", (lo, hi, min_streak))}
    out = {}
    for t in ISSUE_ORDER:
        tp = len({k for k in found if k[3] == t} & truth)
        fp = len({k for k in found if k[3] == t} - truth)
        fn = len({k for k in truth if k[3] == t} - found)
        out[t] = {"precision": tp / (tp + fp) if tp + fp else None, "recall": tp / (tp + fn) if tp + fn else None}
    return out


def multi_seed(cfg: dict, end, days: int, seeds: range) -> dict:
    """Score the rules on many independent simulated fleets, to show how much the numbers move."""
    from . import data, db, engine
    per_type = {t: {"precision": [], "recall": []} for t in ISSUE_ORDER}
    overall = {"precision": [], "recall": []}
    for seed in seeds:
        con = db.connect(":memory:")
        data.backfill(con, end, days, seed=seed)
        engine.run_all(con, cfg)
        r = score(con)
        for t, v in r["types"].items():
            for m in ("precision", "recall"):
                if v[m] is not None:
                    per_type[t][m].append(v[m])
        for m in ("precision", "recall"):
            overall[m].append(r["overall"][m])
        con.close()

    def summ(xs):
        return {"mean": sum(xs) / len(xs), "min": min(xs), "max": max(xs), "n": len(xs)} if xs else None
    return {"seeds": [seeds.start, seeds.stop - 1], "days": days,
            "overall": {m: summ(v) for m, v in overall.items()},
            "types": {t: {m: summ(v) for m, v in d.items()} for t, d in per_type.items()}}


def multi_markdown(res: dict, labels: dict) -> str:
    def f(s):
        return "n/a" if s is None else f"{s['mean'] * 100:.1f}% ({s['min'] * 100:.0f}–{s['max'] * 100:.0f})"
    out = [f"{res['seeds'][1] - res['seeds'][0] + 1} independent simulated fleets (seeds {res['seeds'][0]}–{res['seeds'][1]}), "
           f"{res['days']} days each. Mean, with min–max in brackets.", "",
           "| Issue type | Precision | Recall |", "|---|---:|---:|"]
    for t, v in res["types"].items():
        out.append(f"| {labels[t]} | {f(v['precision'])} | {f(v['recall'])} |")
    out.append(f"| **All types** | **{f(res['overall']['precision'])}** | **{f(res['overall']['recall'])}** |")
    return "\n".join(out)
