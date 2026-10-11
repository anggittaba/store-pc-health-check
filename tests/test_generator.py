from collections import Counter
from datetime import date, timedelta

from pchealth import data, db, generator

END = date(2026, 10, 11)


def test_fleet_shape():
    stores = generator.fleet()
    assert len(stores) == 60
    assert all(1 <= len(s.pcs) <= 3 for s in stores)
    assert len({s.code for s in stores}) == 60
    assert all(not (pc.role == "Back office" and pc.has_edc) for s in stores for pc in s.pcs)


def test_deterministic():
    a = list(generator.simulate(END - timedelta(days=4), END))
    b = list(generator.simulate(END - timedelta(days=4), END))
    assert a == b


def test_every_fault_type_is_injected_over_30_days():
    c = Counter()
    for _, _, truth in generator.simulate(END - timedelta(days=29), END):
        c.update(t["issue_type"] for t in truth)
    assert set(c) == set(generator.ISSUE_TYPES)


def test_missing_pull_means_no_rows_for_that_store():
    for _, rows, truth in generator.simulate(END - timedelta(days=29), END):
        missing = {t["store_code"] for t in truth if t["issue_type"] == "missing_pull"}
        assert not missing & {r["store_code"] for r in rows}


def test_faults_persist_over_several_days():
    runs = Counter()
    seen = {}
    for d, _, truth in generator.simulate(END - timedelta(days=29), END):
        for t in truth:
            k = (t["pc_id"] or t["store_code"], t["issue_type"])
            runs[k] += 1
    assert max(runs.values()) >= 5
    assert sum(1 for v in runs.values() if v >= 3) >= 10


def test_generate_until_only_adds_missing_days():
    con = db.connect(":memory:")
    data.backfill(con, END - timedelta(days=1), 30)
    before = [tuple(r) for r in con.execute("SELECT * FROM snapshots ORDER BY date, pc_id")]
    added = data.generate_until(con, END)
    assert added == [END.isoformat()]
    after = [tuple(r) for r in con.execute("SELECT * FROM snapshots WHERE date < ? ORDER BY date, pc_id", (END.isoformat(),))]
    assert before == after
    assert data.generate_until(con, END) == []
    # the new day equals what a fresh backfill ending on END produces for that day
    fresh = db.connect(":memory:")
    data.backfill(fresh, END, 31)
    q = "SELECT * FROM snapshots WHERE date=? ORDER BY pc_id"
    assert [tuple(r) for r in con.execute(q, (END.isoformat(),))] == [tuple(r) for r in fresh.execute(q, (END.isoformat(),))]
