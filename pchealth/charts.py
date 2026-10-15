"""Inline SVG charts. Colours come from CSS classes so the theme tokens stay in one place."""

from __future__ import annotations

from datetime import date
from html import escape

from markupsafe import Markup


def _d(x: str) -> str:
    v = date.fromisoformat(x)
    return f"{v.day} {v.strftime('%b')}"


def flagged_bars(daily: list[tuple[str, int, int]], today: str, w: int = 560, h: int = 150) -> Markup:
    """30 daily bars: stores flagged (pale) with the high/critical share (ink) on top."""
    if not daily:
        return Markup("")
    top = max(a for _, a, _ in daily) or 1
    n = len(daily)
    gap = 2
    bw = (w - gap * (n - 1)) / n
    base = h - 16
    parts = [f'<svg class="chart bars" viewBox="0 0 {w} {h}" role="img" aria-label="Stores flagged per day, last {n} days">']
    for k, (d, a, r) in enumerate(daily):
        x = k * (bw + gap)
        ha = (a / top) * (base - 4)
        hr = (r / top) * (base - 4)
        cls = " is-today" if d == today else ""
        parts.append(f'<g class="bar{cls}"><title>{_d(d)}: {a} stores flagged, {r} high or critical</title>'
                     f'<rect class="bar-all" x="{x:.1f}" y="{base - ha:.1f}" width="{bw:.1f}" height="{ha:.1f}"/>'
                     f'<rect class="bar-urgent" x="{x:.1f}" y="{base - hr:.1f}" width="{bw:.1f}" height="{hr:.1f}"/></g>')
    parts.append(f'<line class="axis" x1="0" x2="{w}" y1="{base + .5}" y2="{base + .5}"/>')
    parts.append(f'<text class="tick" x="0" y="{h - 2}">{_d(daily[0][0])}</text>')
    parts.append(f'<text class="tick" x="{w}" y="{h - 2}" text-anchor="end">{_d(daily[-1][0])}</text>')
    parts.append("</svg>")
    return Markup("".join(parts))


def type_bars(types, labels) -> list[dict]:
    top = max(types.values(), default=0) or 1
    return [{"type": k, "label": labels[k], "count": v, "pct": round(100 * v / top)}
            for k, v in sorted(types.items(), key=lambda kv: -kv[1])]


def sparkline(values: list[int], w: int = 132, h: int = 26) -> Markup:
    if not values:
        return Markup("")
    top = max(values) or 1
    n = len(values)
    step = w / max(n - 1, 1)
    pts = " ".join(f"{k * step:.1f},{h - 3 - (v / top) * (h - 6):.1f}" for k, v in enumerate(values))
    lx, ly = (n - 1) * step, h - 3 - (values[-1] / top) * (h - 6)
    return Markup(f'<svg class="chart spark" viewBox="0 0 {w} {h}" aria-hidden="true">'
                  f'<polyline points="{pts}"/><circle cx="{lx:.1f}" cy="{ly:.1f}" r="2.2"/></svg>')


METRICS = [
    # field, title, unit, issue type, threshold key, direction (+1: higher is worse)
    ("cpu_temp_c", "CPU temperature", "°C", "overheating", ("overheating", "high_at"), +1),
    ("disk_free_pct", "Disk free", "%", "disk_space", ("disk_space", "medium_at_or_below"), -1),
    ("packet_loss_pct", "Packet loss to gateway", "%", "lan_degraded", ("lan_degraded", "loss_medium_at"), +1),
    ("latency_ms", "Latency to gateway", "ms", "lan_degraded", ("lan_degraded", "latency_medium_at"), +1),
    ("uptime_days", "Days since restart", "d", "no_reboot", ("no_reboot", "low_at"), +1),
    ("ups_battery_pct", "UPS battery", "%", "ups_problem", ("ups_problem", "battery_medium_at_or_below"), -1),
]
STATUS = [
    ("pull", "Health pull", None),
    ("edc_status", "Card terminal", "edc_offline"),
    ("ups_detected", "UPS seen", "ups_problem"),
    ("win_activation", "Activation", "windows_activation"),
    ("smart_status", "Disk self-test", "disk_smart"),
]


def line_chart(series: list[tuple[str, list]], days: list[str], threshold: float, unit: str, flagged: list[set],
               w: int = 560, h: int = 132, title: str = "") -> Markup:
    vals = [v for _, s in series for v in s if v is not None]
    if not vals:
        return Markup('<p class="chart-empty">No readings in this window.</p>')
    lo = min(min(vals), threshold)
    hi = max(max(vals), threshold)
    pad = (hi - lo) * 0.12 or 1
    lo, hi = max(0, lo - pad), hi + pad
    left, right, top_, bottom = 34, 8, 8, 18
    pw, ph = w - left - right, h - top_ - bottom
    n = len(days)

    def X(k):
        return left + (k / max(n - 1, 1)) * pw

    def Y(v):
        return top_ + (1 - (v - lo) / (hi - lo)) * ph

    p = [f'<svg class="chart line" viewBox="0 0 {w} {h}" role="img" aria-label="{escape(title)}, last {len(days)} days, limit {threshold:g}{escape(unit)}">']
    ty = Y(threshold)
    p.append(f'<line class="limit" x1="{left}" x2="{w - right}" y1="{ty:.1f}" y2="{ty:.1f}"/>')
    p.append(f'<text class="tick limit-label" x="{w - right}" y="{ty - 3:.1f}" text-anchor="end">limit {threshold:g}{escape(unit)}</text>')
    for v in (lo, hi):
        p.append(f'<text class="tick" x="{left - 4}" y="{Y(v) + 3:.1f}" text-anchor="end">{v:.0f}</text>')
    for si, ((name, s), fl) in enumerate(zip(series, flagged)):
        segs, cur = [], []
        for k, v in enumerate(s):
            if v is None:
                if cur:
                    segs.append(cur)
                cur = []
            else:
                cur.append(f"{X(k):.1f},{Y(v):.1f}")
        if cur:
            segs.append(cur)
        for seg in segs:
            p.append(f'<polyline class="series s{si}" points="{" ".join(seg)}"/>')
        for k, v in enumerate(s):
            if v is not None and days[k] in fl:
                p.append(f'<circle class="flag s{si}" cx="{X(k):.1f}" cy="{Y(v):.1f}" r="2.6">'
                         f'<title>{escape(name)} · {_d(days[k])}: {v:g}{escape(unit)} (flagged)</title></circle>')
    p.append(f'<text class="tick" x="{left}" y="{h - 3}">{_d(days[0])}</text>')
    p.append(f'<text class="tick" x="{w - right}" y="{h - 3}" text-anchor="end">{_d(days[-1])}</text>')
    p.append("</svg>")
    return Markup("".join(p))


def _status(field: str, row: dict | None, low_battery: float = 40) -> tuple[str, str]:
    if row is None:
        return "missing", "no pull"
    v = row.get(field) if field != "pull" else "ok"
    if field == "pull":
        return "ok", "pulled " + row["pulled_at"][11:16]
    if field == "edc_status":
        return ({"online": "ok", "offline": "bad"}.get(v, "na"), v)
    if field == "ups_detected":
        if not v or row["ups_battery_pct"] is None:
            return "bad", "not detected"
        b = row["ups_battery_pct"]
        return ("warn" if b <= low_battery else "ok"), f"seen · battery {b:g}%"
    if field == "win_activation":
        return ("ok" if v == "Licensed" else "bad", v)
    if field == "smart_status":
        return ("ok" if v == "OK" else "bad", v)
    return "na", str(v)


def store_panels(pcs: list[dict], hist: dict, days: list[str], cfg: dict, flagged: dict) -> dict:
    lines = []
    for field, title, unit, itype, (sec, key), _ in METRICS:
        series, fl = [], []
        for pc in pcs:
            series.append((pc["role"], [hist[pc["pc_id"]].get(d, {}).get(field) for d in days]))
            fl.append(flagged.get((pc["pc_id"], itype), set()))
        lines.append({"title": title, "unit": unit, "type": itype,
                      "svg": line_chart(series, days, float(cfg[sec][key]), unit, fl, title=title)})
    strips = []
    for field, title, itype in STATUS:
        rows = []
        for pc in pcs:
            if field == "edc_status" and pc["role"] == "Back office":
                continue
            cells = []
            for d in days:
                st, tip = _status(field, hist[pc["pc_id"]].get(d), cfg["ups_problem"]["battery_medium_at_or_below"])
                cells.append({"state": st, "tip": f"{_d(d)}: {tip}"})
            rows.append({"role": pc["role"], "cells": cells})
        strips.append({"title": title, "rows": rows})
    return {"lines": lines, "strips": strips, "legend": [pc["role"] for pc in pcs]}


def stacked_types(days: list[str], trend: dict[str, list[int]], labels: dict, order: list[str],
                  w: int = 560, h: int = 150) -> Markup:
    """Issues per day stacked by type; one colour class per type (t-<type>) so the legend matches."""
    if not days:
        return Markup("")
    n = len(days)
    totals = [sum(trend[k][j] for k in order) for j in range(n)]
    top = max(totals) or 1
    left, bottom = 26, 16
    gap = 2
    bw = (w - left - gap * (n - 1)) / n
    base = h - bottom
    ph = base - 6
    p = [f'<svg class="chart stack" viewBox="0 0 {w} {h}" role="img" aria-label="Issues per day by type, last {n} days">']
    for v in (0, top):
        y = base - (v / top) * ph
        p.append(f'<line class="grid" x1="{left}" x2="{w}" y1="{y:.1f}" y2="{y:.1f}"/>')
        p.append(f'<text class="tick" x="{left - 4}" y="{y + 3:.1f}" text-anchor="end">{v}</text>')
    for j, d in enumerate(days):
        x = left + j * (bw + gap)
        y = base
        tip = ", ".join(f"{labels[k]} {trend[k][j]}" for k in order if trend[k][j])
        p.append(f'<g><title>{_d(d)}: {totals[j]} issues{" · " + escape(tip) if tip else ""}</title>')
        for k in order:
            v = trend[k][j]
            if not v:
                continue
            hh = (v / top) * ph
            y -= hh
            p.append(f'<rect class="t-{k}" x="{x:.1f}" y="{y:.1f}" width="{bw:.1f}" height="{hh:.1f}"/>')
        p.append("</g>")
    p.append(f'<text class="tick" x="{left}" y="{h - 2}">{_d(days[0])}</text>')
    p.append(f'<text class="tick" x="{w}" y="{h - 2}" text-anchor="end">{_d(days[-1])}</text>')
    p.append("</svg>")
    return Markup("".join(p))
