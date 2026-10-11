"""Paths and environment. Everything is optional; defaults work out of the box."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_dotenv() -> None:
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


_load_dotenv()


def var_dir() -> Path:
    return Path(os.getenv("PCHEALTH_VAR", ROOT / "var"))


def db_path() -> Path:
    return Path(os.getenv("PCHEALTH_DB", var_dir() / "health.db"))


def rules_path() -> Path:
    return Path(os.getenv("PCHEALTH_RULES", ROOT / "config" / "rules.toml"))


def operator() -> str:
    return os.getenv("PCHEALTH_OPERATOR", "operator")
