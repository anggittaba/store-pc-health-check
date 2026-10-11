from datetime import date

from pchealth import data, db, engine, evaluate, rules
from tests.conftest import END


def test_run_all_produces_one_ok_run_per_day(filled):
    assert len(db.dates(filled)) == 30
    assert filled.execute("SELECT COUNT(*) FROM runs WHERE status='ok'").fetchone()[0] == 30


def test_idempotent_rerun(filled, cfg):
    d = END.isoformat()
    before = [tuple(r) for r in filled.execute("SELECT * FROM issues WHERE date=? ORDER BY store_code, pc_id, issue_type", (d,))]
    res = engine.run_day(filled, cfg, d)
    after = [tuple(r) for r in filled.execute("SELECT * FROM issues WHERE date=? ORDER BY store_code, pc_id, issue_type", (d,))]
    assert before == after and res.replaced
    last = filled.execute("SELECT replaced FROM runs ORDER BY id DESC LIMIT 1").fetchone()[0]
    assert last == 1


def test_missing_pull_flagged_for_every_silent_store(filled):
    for d in db.dates(filled):
        silent = {r[0] for r in filled.execute("SELECT code FROM stores")} - {
            r[0] for r in filled.execute("SELECT DISTINCT store_code FROM snapshots WHERE date=?", (d,))}
        flagged = {r[0] for r in filled.execute("SELECT store_code FROM issues WHERE date=? AND issue_type='missing_pull'", (d,))}
        assert silent == flagged


def test_streaks_count_consecutive_days(filled):
    rows = filled.execute("SELECT * FROM issues WHERE streak >= 3 LIMIT 20").fetchall()
    assert rows
    for r in rows:
        prev = filled.execute("SELECT streak FROM issues WHERE date=date(?, '-1 day') AND store_code=? AND "
                              "IFNULL(pc_id,'')=IFNULL(?, '') AND issue_type=?",
                              (r["date"], r["store_code"], r["pc_id"], r["issue_type"])).fetchone()
        if prev is not None:
            assert prev["streak"] == r["streak"] - 1


def test_missing_pull_streak_carries_over(filled):
    assert filled.execute("SELECT COUNT(*) FROM issues WHERE issue_type='missing_pull' AND streak >= 2").fetchone()[0] > 0


def test_recurring_issues_are_raised_one_level(filled, cfg):
    no_esc = set(cfg["general"]["no_escalation"])
    for r in filled.execute("SELECT * FROM issues"):
        if r["streak"] >= cfg["general"]["recurring_after_days"] and r["issue_type"] not in no_esc:
            assert r["severity"] == rules.bump(r["base_severity"])
        else:
            assert r["severity"] == r["base_severity"]


def test_new_and_resolved_are_consistent(filled):
    for d in db.dates(filled)[1:]:
        today = {(r["store_code"], r["pc_id"] or "", r["issue_type"]): r for r in filled.execute("SELECT * FROM issues WHERE date=?", (d,))}
        for k, r in today.items():
            assert (r["is_new"] == 1) == (r["streak"] == 1)
        for r in filled.execute("SELECT * FROM resolved WHERE date=?", (d,)):
            assert (r["store_code"], r["pc_id"] or "", r["issue_type"]) not in today


def test_no_resolved_for_a_store_without_data(filled):
    bad = filled.execute("SELECT COUNT(*) FROM resolved r JOIN issues i ON i.date=r.date AND i.store_code=r.store_code "
                         "AND i.issue_type='missing_pull'").fetchone()[0]
    assert bad == 0


def test_cannot_run_a_day_without_data(filled, cfg):
    import pytest
    with pytest.raises(ValueError):
        engine.run_day(filled, cfg, "2030-01-01")


def test_evaluation_counts_add_up(filled):
    res = evaluate.score(filled)
    o = res["overall"]
    issues = filled.execute("SELECT COUNT(*) FROM issues").fetchone()[0]
    assert o["true_pos"] + o["false_pos"] == issues
    assert 0.5 < o["precision"] <= 1 and 0.5 < o["recall"] <= 1
    for t, v in res["types"].items():
        assert v["hidden_by_missing_pull"] <= v["false_neg"]
