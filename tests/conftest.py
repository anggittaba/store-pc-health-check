from datetime import date

import pytest

from pchealth import data, db, engine, rules, settings

END = date(2026, 10, 11)


@pytest.fixture(scope="session")
def cfg():
    return rules.load_rules(settings.ROOT / "config" / "rules.toml")


@pytest.fixture()
def con():
    c = db.connect(":memory:")
    yield c
    c.close()


@pytest.fixture(scope="session")
def filled(cfg, tmp_path_factory):
    """A 30-day synthetic history with every day already run (shared, read-only in tests)."""
    path = tmp_path_factory.mktemp("db") / "health.db"
    c = db.connect(path)
    data.backfill(c, END, 30)
    engine.run_all(c, cfg)
    return c


def snap(**over):
    base = {"date": "2026-10-11", "store_code": "ST-001", "pc_id": "ST-001-PC1", "role": "Till 1",
            "pulled_at": "2026-10-11T05:10:00", "cpu_model": "Core i3-10100", "cpu_temp_c": 55.0, "ram_gb": 8,
            "ram_spec_gb": 8, "disk_total_gb": 256, "disk_free_pct": 40.0, "os_build": "Windows 11 Pro 23H2 (22631)",
            "lan_link": "up", "lan_speed_mbps": 1000, "packet_loss_pct": 0.1, "latency_ms": 3.0,
            "last_boot": "2026-10-10T22:00:00", "uptime_days": 0.3, "win_activation": "Licensed",
            "edc_status": "online", "ups_detected": 1, "ups_battery_pct": 97, "smart_status": "OK"}
    base.update(over)
    return base
