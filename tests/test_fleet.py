from pchealth import fleet
from tests.conftest import END


def _i(t, s):
    return {"issue_type": t, "severity": s}


def test_store_status_buckets():
    assert fleet.store_status([]) == "healthy"
    assert fleet.store_status([_i("no_reboot", "low")]) == "warning"
    assert fleet.store_status([_i("no_reboot", "low"), _i("disk_space", "medium")]) == "warning"
    assert fleet.store_status([_i("no_reboot", "low"), _i("edc_offline", "high")]) == "critical"
    assert fleet.store_status([_i("lan_degraded", "critical")]) == "critical"
    assert fleet.store_status([_i("missing_pull", "high")]) == "nodata"


def test_every_issue_type_has_a_tile_tag():
    from pchealth.rules import ISSUE_ORDER
    assert set(fleet.TAG) == set(ISSUE_ORDER)


def test_pc_counts_cover_every_pc(filled):
    day = END.isoformat()
    c = fleet.pc_status_counts(filled, day)
    n = filled.execute("SELECT COUNT(*) FROM pcs").fetchone()[0]
    assert sum(c.values()) == n
    reported = filled.execute("SELECT COUNT(*) FROM snapshots WHERE date=?", (day,)).fetchone()[0]
    assert c["nodata"] == n - reported


def test_store_counts_match_issue_table(filled):
    day = END.isoformat()
    c = fleet.store_status_counts(filled, day)
    stores = filled.execute("SELECT COUNT(*) FROM stores").fetchone()[0]
    flagged = filled.execute("SELECT COUNT(DISTINCT store_code) FROM issues WHERE date=?", (day,)).fetchone()[0]
    missing = filled.execute("SELECT COUNT(*) FROM issues WHERE date=? AND issue_type='missing_pull'", (day,)).fetchone()[0]
    assert sum(c.values()) == stores
    assert c["healthy"] == stores - flagged
    assert c["nodata"] == missing


def test_kpis_have_deltas(filled):
    from datetime import timedelta
    k = fleet.kpis(filled, END.isoformat(), (END - timedelta(days=1)).isoformat())
    assert [x["key"] for x in k] == ["healthy", "warning", "critical", "nodata"]
    assert all(x["delta"] is not None for x in k)
    assert fleet.kpis(filled, END.isoformat(), None)[0]["delta"] is None


def test_type_trend_sums_to_issue_count(filled):
    days = [END.isoformat()]
    tt = fleet.type_trend(filled, days)
    n = filled.execute("SELECT COUNT(*) FROM issues WHERE date=?", days).fetchone()[0]
    assert sum(v[0] for v in tt.values()) == n
