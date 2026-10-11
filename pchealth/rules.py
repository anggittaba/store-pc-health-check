"""Deterministic health rules. Each finding carries the reading, the limit it broke and a reason.

No AI is involved here: the same snapshot and the same config/rules.toml always give the same issues.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

SEVERITIES = ["low", "medium", "high", "critical"]
RANK = {s: i for i, s in enumerate(SEVERITIES)}
ISSUE_ORDER = ["missing_pull", "edc_offline", "lan_degraded", "overheating", "disk_smart", "disk_space",
               "ups_problem", "ram_below_spec", "no_reboot", "windows_activation"]


@dataclass
class Finding:
    issue_type: str
    severity: str
    value: str
    threshold: str
    reason: str
    metric: float | None = None  # numeric reading used for trends


def load_rules(path: Path) -> dict:
    with open(path, "rb") as f:
        cfg = tomllib.load(f)
    missing = [t for t in ISSUE_ORDER if t not in cfg or t not in cfg.get("playbook", {})]
    missing += [p for p in ("ups_battery",) if p not in cfg.get("playbook", {})]
    if missing:
        raise ValueError(f"rules file has no thresholds or playbook for: {', '.join(missing)}")
    return cfg


def label(cfg: dict, issue_type: str) -> str:
    return cfg[issue_type]["label"]


def bump(severity: str) -> str:
    return SEVERITIES[min(RANK[severity] + 1, len(SEVERITIES) - 1)]


def _fmt(v: float, unit: str = "") -> str:
    return f"{v:g}{unit}"


def check_pc(s: dict, cfg: dict) -> list[Finding]:
    """All findings for one PC's daily snapshot (a dict with the snapshot columns)."""
    out: list[Finding] = []

    c = cfg["overheating"]
    t = s["cpu_temp_c"]
    if t is not None and t >= c["high_at"]:
        sev = "critical" if t >= c["critical_at"] else "high"
        lim = c["critical_at"] if sev == "critical" else c["high_at"]
        out.append(Finding("overheating", sev, _fmt(t, " °C"), f"≥ {lim} °C",
                           f"CPU at {t:g} °C, limit {c['high_at']} °C", t))

    c = cfg["disk_space"]
    free = s["disk_free_pct"]
    if free is not None and free <= c["medium_at_or_below"]:
        sev = "high" if free <= c["high_at_or_below"] else "medium"
        lim = c["high_at_or_below"] if sev == "high" else c["medium_at_or_below"]
        gb = s["disk_total_gb"] * free / 100 if s.get("disk_total_gb") else None
        extra = f" ({gb:.0f} GB of {s['disk_total_gb']} GB)" if gb is not None else ""
        out.append(Finding("disk_space", sev, _fmt(free, "% free"), f"≤ {lim}% free",
                           f"{free:g}% free{extra}, limit {c['medium_at_or_below']}%", free))

    c = cfg["ram_below_spec"]
    expected = s.get("ram_spec_gb") or c["minimum_gb"]
    expected = max(expected, c["minimum_gb"])
    if s["ram_gb"] is not None and s["ram_gb"] < expected:
        out.append(Finding("ram_below_spec", "medium", f"{s['ram_gb']} GB", f"{expected} GB spec",
                           f"{s['ram_gb']} GB installed, spec is {expected} GB", s["ram_gb"]))

    c = cfg["no_reboot"]
    up = s["uptime_days"]
    if up is not None and up >= c["low_at"]:
        sev = "medium" if up >= c["medium_at"] else "low"
        out.append(Finding("no_reboot", sev, f"{up:.0f} days up", f"≥ {c['low_at']} days",
                           f"last restart {up:.0f} days ago, limit {c['low_at']} days", up))

    c = cfg["windows_activation"]
    act = s["win_activation"]
    if act not in c["ok_values"]:
        sev = "medium" if act in c["medium_values"] else "low"
        out.append(Finding("windows_activation", sev, act or "unknown", "Licensed",
                           f"activation status is '{act}', expected Licensed"))

    c = cfg["edc_offline"]
    if s["edc_status"] == "offline":
        out.append(Finding("edc_offline", c["offline_severity"], "offline", "online",
                           "card terminal did not answer at the pull"))

    c = cfg["ups_problem"]
    if not s["ups_detected"]:
        out.append(Finding("ups_problem", c["not_detected_severity"], "not detected", "detected",
                           "no UPS seen by the PC"))
    elif s["ups_battery_pct"] is not None and s["ups_battery_pct"] <= c["battery_medium_at_or_below"]:
        b = s["ups_battery_pct"]
        sev = "high" if b <= c["battery_high_at_or_below"] else "medium"
        lim = c["battery_high_at_or_below"] if sev == "high" else c["battery_medium_at_or_below"]
        out.append(Finding("ups_problem", sev, _fmt(b, "% battery"), f"≤ {lim}%",
                           f"UPS battery at {b:g}%, limit {c['battery_medium_at_or_below']}%", b))

    c = cfg["lan_degraded"]
    if s["lan_link"] == "down":
        out.append(Finding("lan_degraded", c["link_down_severity"], "link down", "link up",
                           "network link is down", 100.0))
    else:
        parts, sev = [], None
        loss, lat, speed = s["packet_loss_pct"], s["latency_ms"], s["lan_speed_mbps"]
        if loss is not None and loss >= c["loss_medium_at"]:
            parts.append(f"{loss:g}% packet loss (limit {c['loss_medium_at']}%)")
            sev = "medium"
        if lat is not None and lat >= c["latency_medium_at"]:
            parts.append(f"{lat:.0f} ms to gateway (limit {c['latency_medium_at']} ms)")
            sev = "medium"
        if speed is not None and 0 < speed < c["expected_speed_mbps"]:
            parts.append(f"link at {speed} Mbps, expected {c['expected_speed_mbps']}")
            sev = sev or c["slow_link_severity"]
        if parts:
            value = f"{loss:g}% loss · {lat:.0f} ms · {speed} Mbps" if lat is not None else f"{loss:g}% loss"
            out.append(Finding("lan_degraded", sev, value,
                               f"< {c['loss_medium_at']}% · < {c['latency_medium_at']} ms · {c['expected_speed_mbps']} Mbps",
                               "; ".join(parts), loss))

    c = cfg["disk_smart"]
    if s["smart_status"] in ("Caution", "Bad"):
        sev = c["bad_severity"] if s["smart_status"] == "Bad" else c["caution_severity"]
        out.append(Finding("disk_smart", sev, s["smart_status"], "OK", f"disk self-test reports '{s['smart_status']}'"))
    return out


# Which direction is "worse" for the trend check, per issue type.
TREND = {"overheating": +1, "disk_space": -1, "ups_problem": -1, "lan_degraded": +1}
TREND_FIELD = {"overheating": "cpu_temp_c", "disk_space": "disk_free_pct", "ups_problem": "ups_battery_pct",
               "lan_degraded": "packet_loss_pct"}


def trend(values: list[float | None], issue_type: str, cfg: dict) -> str | None:
    """'worsening' / 'improving' when the last N readings all move one way by at least min_step."""
    if issue_type not in TREND:
        return None
    n = cfg["general"]["trend_window_days"]
    vals = values[-n:]
    if len(vals) < n or any(v is None for v in vals):
        return None
    step = cfg[issue_type].get("trend_min_step", 0)
    diffs = [(b - a) * TREND[issue_type] for a, b in zip(vals, vals[1:])]
    if all(d >= step for d in diffs):
        return "worsening"
    if all(d <= -step for d in diffs):
        return "improving"
    return "stable"


def playbook_for(cfg: dict, issue: dict) -> dict:
    """The handling playbook for one issue; a few types have a variant chosen by the reading."""
    if issue["issue_type"] == "ups_problem" and "battery" in (issue.get("value") or ""):
        return cfg["playbook"]["ups_battery"]
    return cfg["playbook"][issue["issue_type"]]
