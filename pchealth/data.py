"""Load synthetic pulls into the database: a 30-day backfill, or just the missing days up to today."""

from __future__ import annotations

from datetime import date, timedelta

from . import db, generator

SNAP_COLS = ["date", "store_code", "pc_id", "role", "pulled_at", "cpu_model", "cpu_temp_c", "ram_gb", "ram_spec_gb",
             "disk_total_gb", "disk_free_pct", "os_build", "lan_link", "lan_speed_mbps", "packet_loss_pct",
             "latency_ms", "last_boot", "uptime_days", "win_activation", "edc_status", "ups_detected",
             "ups_battery_pct", "smart_status"]


def _write_fleet(con, seed: int) -> None:
    for s in generator.fleet(seed):
        con.execute("INSERT OR REPLACE INTO stores VALUES (?,?,?)", (s.code, s.name, s.area))
        for pc in s.pcs:
            con.execute("INSERT OR REPLACE INTO pcs VALUES (?,?,?,?)", (pc.pc_id, s.code, pc.role, pc.ram_spec))


def _insert_day(con, day: date, rows: list[dict], truth: list[dict]) -> None:
    d = day.isoformat()
    con.execute("DELETE FROM snapshots WHERE date=?", (d,))
    con.execute("DELETE FROM ground_truth WHERE date=?", (d,))
    con.executemany(f"INSERT INTO snapshots ({','.join(SNAP_COLS)}) VALUES ({','.join('?' * len(SNAP_COLS))})",
                    [[r[c] for c in SNAP_COLS] for r in rows])
    con.executemany("INSERT INTO ground_truth VALUES (?,?,?,?)",
                    [(t["date"], t["store_code"], t["pc_id"], t["issue_type"]) for t in truth])
    db.set_meta(con, f"day:{d}", d)


def backfill(con, end: date, days: int = 30, seed: int = generator.SEED) -> list[str]:
    """Start a fresh history of `days` days ending on `end` (wipes earlier synthetic data)."""
    for t in ("snapshots", "ground_truth", "issues", "resolved", "runs", "resumes", "handled", "stores", "pcs"):
        con.execute(f"DELETE FROM {t}")
    con.execute("DELETE FROM meta")
    con.execute("DELETE FROM sqlite_sequence")
    start = end - timedelta(days=days - 1)
    db.set_meta(con, "sim_start", start.isoformat())
    db.set_meta(con, "seed", seed)
    _write_fleet(con, seed)
    out = []
    for day, rows, truth in generator.simulate(start, end, seed):
        _insert_day(con, day, rows, truth)
        out.append(day.isoformat())
    con.commit()
    return out


def generate_until(con, end: date) -> list[str]:
    """Add the pulls for every day after the last stored one, up to `end`. Existing days are untouched."""
    start = db.get_meta(con, "sim_start")
    if start is None:
        return backfill(con, end)
    seed = int(db.get_meta(con, "seed", generator.SEED))
    have = set(db.snapshot_dates(con))
    added = []
    for day, rows, truth in generator.simulate(date.fromisoformat(start), end, seed):
        if day.isoformat() not in have:
            _insert_day(con, day, rows, truth)
            added.append(day.isoformat())
    con.commit()
    return added
