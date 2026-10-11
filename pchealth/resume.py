"""The daily recap (resume) and a plain-English explanation per flagged store.

Default writer: fixed templates over the rule results (no network, no key).
Optional writer: an LLM via OpenAI or Gemini. Its output is only accepted if every number
it uses appears in the facts it was given and it covers every flagged store; otherwise the
template text is kept. The recap is shown with a copy button and is never sent anywhere.
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import date

from .rules import ISSUE_ORDER, RANK, playbook_for

MAX_PRIORITIES = 6
ROLE_ISSUES = {"edc_offline", "lan_degraded", "overheating", "disk_smart", "disk_space", "ups_problem",
               "ram_below_spec", "no_reboot", "windows_activation"}


def nice_date(d: str) -> str:
    x = date.fromisoformat(d)
    return f"{x.strftime('%a')} {x.day} {x.strftime('%b %Y')}"


def ordinal(n: int) -> str:
    suf = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suf}"


def where(i: dict, pcs: dict) -> str:
    if not i["pc_id"]:
        return "whole store"
    return pcs.get(i["pc_id"], {}).get("role", i["pc_id"])


def low(label: str) -> str:
    """Lower-case a label for use mid-sentence, keeping acronyms and product names."""
    first = label.split()[0]
    if first.isupper() or first == "Windows":
        return label
    return label[0].lower() + label[1:]


def issue_line(i: dict, cfg: dict, pcs: dict) -> str:
    lab = low(cfg[i["issue_type"]]["label"])
    s = f"{lab} on {where(i, pcs)}" if i["pc_id"] else lab
    s += f" ({i['value']})" if i["issue_type"] not in ("edc_offline", "missing_pull") else ""
    if i["streak"] >= 2:
        s += f", {ordinal(i['streak'])} day in a row"
    if i.get("trend") == "worsening":
        s += ", getting worse"
    return s


def group_by_store(issues: list[dict]) -> dict[str, list[dict]]:
    by = defaultdict(list)
    for i in issues:
        by[i["store_code"]].append(i)
    return by


def store_rank(items: list[dict]):
    top = items[0]
    return (-RANK[top["severity"]], ISSUE_ORDER.index(top["issue_type"]), -top["streak"], top["store_code"])


def explain_store(code: str, items: list[dict], stores: dict, cfg: dict, pcs: dict) -> str:
    top = items[0]
    pb = playbook_for(cfg, top)
    name = stores[code]["name"]
    first = issue_line(top, cfg, pcs)
    text = f"{name} ({code}): {first[0].upper() + first[1:]}. {pb['impact']}"
    text += f" First step ({pb['owner']}): {pb['steps'][0]}"
    others = items[1:]
    if others:
        labs = [low(cfg[o["issue_type"]]["label"]) for o in others]
        uniq = list(dict.fromkeys(labs))
        text += f" Also flagged: {', '.join(uniq)}."
    return text


def template(cfg: dict, day: str, issues: list[dict], resolved: list[dict], stores: dict, pcs: dict,
             stats: dict) -> tuple[str, dict]:
    by = group_by_store(issues)
    order = sorted(by, key=lambda c: store_rank(by[c]))
    sev = Counter(by[c][0]["severity"] for c in order)
    missing = [i for i in issues if i["issue_type"] == "missing_pull"]
    lines = [f"PC health recap · {nice_date(day)}",
             f"{stats['pcs_reported']} of {stats['pcs_expected']} store PCs reported. "
             f"{len(missing)} {'store' if len(missing) == 1 else 'stores'} sent no data.",
             f"{len(order)} stores flagged: {sev['critical']} critical, {sev['high']} high, "
             f"{sev['medium']} medium, {sev['low']} low (by their worst issue).", ""]
    urgent = [c for c in order if RANK[by[c][0]["severity"]] >= RANK["high"]][:MAX_PRIORITIES]
    if urgent:
        lines.append("Do first")
        for n, c in enumerate(urgent, 1):
            top = by[c][0]
            pb = playbook_for(cfg, top)
            lines.append(f"{n}. {c} {stores[c]['name']}: {issue_line(top, cfg, pcs)} [{top['severity']}]. "
                         f"{pb['owner']}: {pb['steps'][0]}")
        rest = len([c for c in order if RANK[by[c][0]["severity"]] >= RANK["high"]]) - len(urgent)
        if rest > 0:
            lines.append(f"…and {rest} more high-priority {'store' if rest == 1 else 'stores'} on the dashboard.")
        lines.append("")
    new = [i for i in issues if i["is_new"]]
    if new:
        cnt = Counter(low(cfg[i["issue_type"]]["label"]) for i in new)
        lines.append(f"New since yesterday ({len(new)}): " + ", ".join(f"{k} ×{v}" if v > 1 else k for k, v in cnt.most_common()))
    if resolved:
        cnt = Counter(low(cfg[r["issue_type"]]["label"]) for r in resolved)
        lines.append(f"Cleared since yesterday ({len(resolved)}): " + ", ".join(f"{k} ×{v}" if v > 1 else k for k, v in cnt.most_common()))
    rec_after = cfg["general"]["recurring_after_days"]
    recurring = [i for i in issues if i["streak"] >= rec_after and i["issue_type"] not in cfg["general"]["no_escalation"]]
    if recurring:
        lines.append(f"Recurring, {rec_after}+ days ({len(recurring)}): " + ", ".join(
            f"{i['store_code']} {low(cfg[i['issue_type']]['label'])} ({i['streak']}d)" for i in recurring[:8])
            + (" …" if len(recurring) > 8 else ""))
    if missing:
        lines.append("No data: " + ", ".join(
            f"{i['store_code']}" + (f" ({ordinal(i['streak'])} day)" if i["streak"] > 1 else "") for i in missing))
    owners = Counter(playbook_for(cfg, i)["owner"] for i in issues)
    if owners:
        lines.append("Work by owner: " + " · ".join(f"{o} {owners[o]}" for o in ("Store staff", "Remote IT", "Vendor") if owners[o]))
    lines += ["", "Drafted from the rule results. Check it before you send it."]
    explanations = {c: explain_store(c, by[c], stores, cfg, pcs) for c in order}
    return "\n".join(lines), explanations


NUM = re.compile(r"\d+(?:\.\d+)?")


def _numbers(text: str) -> set[str]:
    return {n.rstrip("0").rstrip(".") if "." in n else n for n in NUM.findall(text)}


def facts_for_llm(cfg, day, issues, resolved, stores, pcs, stats) -> dict:
    by = group_by_store(issues)
    order = sorted(by, key=lambda c: store_rank(by[c]))[:20]
    return {
        "date": day, "pcs_expected": stats["pcs_expected"], "pcs_reported": stats["pcs_reported"],
        "stores_flagged": len(by), "stores_without_data": [i["store_code"] for i in issues if i["issue_type"] == "missing_pull"],
        "stores": [{
            "store_code": c, "store_name": stores[c]["name"],
            "issues": [{"issue": cfg[i["issue_type"]]["label"], "where": where(i, pcs), "severity": i["severity"],
                        "reading": i["value"], "rule": i["reason"], "days_in_a_row": i["streak"],
                        "trend": i["trend"], "owner": playbook_for(cfg, i)["owner"],
                        "first_step": playbook_for(cfg, i)["steps"][0],
                        "why_it_matters": playbook_for(cfg, i)["impact"]} for i in by[c]],
        } for c in order],
        "new_since_yesterday": len([i for i in issues if i["is_new"]]),
        "resolved_since_yesterday": [{"store_code": r["store_code"], "issue": cfg[r["issue_type"]]["label"]} for r in resolved],
    }


def from_llm(provider, facts: dict) -> tuple[str, dict]:
    from .llm import RESUME_PROMPT, RESUME_SCHEMA
    out = provider.complete(RESUME_PROMPT, json.dumps(facts), RESUME_SCHEMA, "daily_resume")
    allowed = _numbers(json.dumps(facts)) | {str(n) for n in range(0, 11)}
    summary = (out.get("summary") or "").strip()
    stores = {s.get("store_code"): (s.get("explanation") or "").strip() for s in out.get("stores", [])}
    want = [s["store_code"] for s in facts["stores"]]
    if not summary or any(not stores.get(c) for c in want):
        raise ValueError("model output is missing the summary or a store")
    texts = [summary] + [stores[c] for c in want]
    extra = set().union(*(_numbers(t) for t in texts)) - allowed
    if extra:
        raise ValueError(f"model output has numbers not in the facts: {sorted(extra)[:5]}")
    return summary, {c: stores[c] for c in want}


def write(con, cfg, day, issues, resolved, stores, provider=None) -> tuple[str, dict, str]:
    pcs = {r["pc_id"]: dict(r) for r in con.execute("SELECT * FROM pcs")}
    stats = {"pcs_expected": len(pcs),
             "pcs_reported": con.execute("SELECT COUNT(*) FROM snapshots WHERE date=?", (day,)).fetchone()[0]}
    text, expl = template(cfg, day, issues, resolved, stores, pcs, stats)
    if provider is None or not issues:
        return text, expl, "template"
    try:
        summary, llm_expl = from_llm(provider, facts_for_llm(cfg, day, issues, resolved, stores, pcs, stats))
    except Exception as e:  # network, quota, bad JSON, failed checks: keep the template
        return text, expl, f"template (AI output rejected: {type(e).__name__})"
    expl.update(llm_expl)
    return summary + "\n\nDrafted by AI from the rule results. Check it before you send it.", expl, provider.name
