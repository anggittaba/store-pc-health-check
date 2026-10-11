import pytest

from pchealth import rules
from tests.conftest import snap


def types(findings):
    return {f.issue_type: f for f in findings}


def test_healthy_pc_has_no_findings(cfg):
    assert rules.check_pc(snap(), cfg) == []


@pytest.mark.parametrize("temp,sev", [(84.9, None), (85, "high"), (94.9, "high"), (95, "critical")])
def test_overheating_thresholds(cfg, temp, sev):
    f = types(rules.check_pc(snap(cpu_temp_c=temp), cfg)).get("overheating")
    assert (f.severity if f else None) == sev


def test_reason_shows_value_and_limit(cfg):
    f = types(rules.check_pc(snap(cpu_temp_c=91.2), cfg))["overheating"]
    assert "91.2" in f.reason and "85" in f.reason
    assert f.value == "91.2 °C" and f.threshold == "≥ 85 °C"


@pytest.mark.parametrize("free,sev", [(10.1, None), (10, "medium"), (3.1, "medium"), (3, "high")])
def test_disk_space(cfg, free, sev):
    f = types(rules.check_pc(snap(disk_free_pct=free), cfg)).get("disk_space")
    assert (f.severity if f else None) == sev


def test_ram_below_spec_uses_pc_spec(cfg):
    assert "ram_below_spec" in types(rules.check_pc(snap(ram_gb=8, ram_spec_gb=16), cfg))
    assert "ram_below_spec" not in types(rules.check_pc(snap(ram_gb=16, ram_spec_gb=16), cfg))
    assert "ram_below_spec" in types(rules.check_pc(snap(ram_gb=4, ram_spec_gb=4), cfg))  # global minimum 8 GB


@pytest.mark.parametrize("up,sev", [(6.9, None), (7, "low"), (21, "medium")])
def test_no_reboot(cfg, up, sev):
    f = types(rules.check_pc(snap(uptime_days=up), cfg)).get("no_reboot")
    assert (f.severity if f else None) == sev


@pytest.mark.parametrize("act,sev", [("Licensed", None), ("Notification", "low"), ("Unlicensed", "medium")])
def test_activation(cfg, act, sev):
    f = types(rules.check_pc(snap(win_activation=act), cfg)).get("windows_activation")
    assert (f.severity if f else None) == sev


def test_edc_offline_is_high_and_back_office_ignored(cfg):
    assert types(rules.check_pc(snap(edc_status="offline"), cfg))["edc_offline"].severity == "high"
    assert rules.check_pc(snap(edc_status="n/a"), cfg) == []


def test_ups(cfg):
    assert types(rules.check_pc(snap(ups_detected=0, ups_battery_pct=None), cfg))["ups_problem"].value == "not detected"
    assert types(rules.check_pc(snap(ups_battery_pct=40), cfg))["ups_problem"].severity == "medium"
    assert types(rules.check_pc(snap(ups_battery_pct=20), cfg))["ups_problem"].severity == "high"
    assert "ups_problem" not in types(rules.check_pc(snap(ups_battery_pct=41), cfg))


def test_lan(cfg):
    assert types(rules.check_pc(snap(lan_link="down", lan_speed_mbps=0, packet_loss_pct=100, latency_ms=None), cfg))[
        "lan_degraded"].severity == "critical"
    f = types(rules.check_pc(snap(packet_loss_pct=6.0, latency_ms=140), cfg))["lan_degraded"]
    assert f.severity == "medium" and "6% packet loss" in f.reason and "140 ms" in f.reason
    assert types(rules.check_pc(snap(lan_speed_mbps=100), cfg))["lan_degraded"].severity == "low"
    assert "lan_degraded" not in types(rules.check_pc(snap(packet_loss_pct=4.9, latency_ms=99), cfg))


def test_smart(cfg):
    assert types(rules.check_pc(snap(smart_status="Caution"), cfg))["disk_smart"].severity == "high"
    assert types(rules.check_pc(snap(smart_status="Bad"), cfg))["disk_smart"].severity == "critical"


def test_thresholds_come_from_config(cfg):
    import copy
    c = copy.deepcopy(cfg)
    c["overheating"]["high_at"] = 70
    assert "overheating" in types(rules.check_pc(snap(cpu_temp_c=72), c))
    assert "overheating" not in types(rules.check_pc(snap(cpu_temp_c=72), cfg))


def test_trend(cfg):
    assert rules.trend([80, 84, 90], "overheating", cfg) == "worsening"
    assert rules.trend([90, 86, 82], "overheating", cfg) == "improving"
    assert rules.trend([80, 85, 84], "overheating", cfg) == "stable"
    assert rules.trend([12, 8, 4], "disk_space", cfg) == "worsening"  # free space falling is worse
    assert rules.trend([80, 90], "overheating", cfg) is None
    assert rules.trend([1, 2, 3], "edc_offline", cfg) is None


def test_bump_caps_at_critical():
    assert rules.bump("low") == "medium" and rules.bump("critical") == "critical"


def test_every_issue_type_has_playbook_with_owner(cfg):
    for t in rules.ISSUE_ORDER:
        pb = cfg["playbook"][t]
        assert pb["owner"] in ("Store staff", "Remote IT", "Vendor")
        assert len(pb["steps"]) >= 2 and pb["impact"] and pb["escalate"]


def test_ups_battery_variant_playbook(cfg):
    assert rules.playbook_for(cfg, {"issue_type": "ups_problem", "value": "22% battery"})["owner"] == "Vendor"
    assert rules.playbook_for(cfg, {"issue_type": "ups_problem", "value": "not detected"})["owner"] == "Store staff"


def test_missing_rules_rejected(tmp_path):
    p = tmp_path / "r.toml"
    p.write_text('[general]\nrecurring_after_days = 3\n')
    with pytest.raises(ValueError):
        rules.load_rules(p)
