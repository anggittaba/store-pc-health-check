"""SQLite storage: stores, PCs, daily snapshots, injected-fault labels, issues, runs and notes."""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS stores (code TEXT PRIMARY KEY, name TEXT, area TEXT);
CREATE TABLE IF NOT EXISTS pcs (pc_id TEXT PRIMARY KEY, store_code TEXT, role TEXT, ram_spec_gb INTEGER);
CREATE TABLE IF NOT EXISTS snapshots (
  date TEXT, store_code TEXT, pc_id TEXT, role TEXT, pulled_at TEXT, cpu_model TEXT, cpu_temp_c REAL,
  ram_gb INTEGER, ram_spec_gb INTEGER, disk_total_gb INTEGER, disk_free_pct REAL, os_build TEXT,
  lan_link TEXT, lan_speed_mbps INTEGER, packet_loss_pct REAL, latency_ms REAL, last_boot TEXT, uptime_days REAL,
  win_activation TEXT, edc_status TEXT, ups_detected INTEGER, ups_battery_pct REAL, smart_status TEXT,
  PRIMARY KEY (date, pc_id)
);
CREATE TABLE IF NOT EXISTS ground_truth (date TEXT, store_code TEXT, pc_id TEXT, issue_type TEXT);
CREATE INDEX IF NOT EXISTS gt_date ON ground_truth(date);
CREATE TABLE IF NOT EXISTS issues (
  date TEXT, store_code TEXT, pc_id TEXT, issue_type TEXT, severity TEXT, base_severity TEXT,
  value TEXT, threshold TEXT, reason TEXT, streak INTEGER, trend TEXT, is_new INTEGER
);
CREATE INDEX IF NOT EXISTS issues_date ON issues(date);
CREATE TABLE IF NOT EXISTS resolved (date TEXT, store_code TEXT, pc_id TEXT, issue_type TEXT, open_days INTEGER);
CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT, run_date TEXT, started_at TEXT, finished_at TEXT, trigger TEXT,
  pcs_expected INTEGER, pcs_reported INTEGER, stores_missing INTEGER, issues INTEGER, stores_flagged INTEGER,
  new INTEGER, resolved INTEGER, writer TEXT, replaced INTEGER, status TEXT
);
CREATE TABLE IF NOT EXISTS resumes (date TEXT PRIMARY KEY, writer TEXT, text TEXT, explanations TEXT);
CREATE TABLE IF NOT EXISTS handled (
  id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT, store_code TEXT, issue_type TEXT, note TEXT, by TEXT, at TEXT
);
"""


def connect(path: Path | str) -> sqlite3.Connection:
    path = Path(path)
    if str(path) != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path), check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def get_meta(con, key: str, default=None):
    r = con.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return r["value"] if r else default


def set_meta(con, key: str, value) -> None:
    con.execute("INSERT INTO meta(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, str(value)))


def dates(con) -> list[str]:
    return [r[0] for r in con.execute("SELECT DISTINCT run_date FROM runs ORDER BY run_date")]


def snapshot_dates(con) -> list[str]:
    return [r[0] for r in con.execute("SELECT value FROM meta WHERE key LIKE 'day:%' ORDER BY value")]
