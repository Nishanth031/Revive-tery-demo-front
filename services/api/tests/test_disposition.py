"""Reuse / repurpose / recycle mapping (config/decision_map.json) for each engine decision."""
from revive_api.disposition import disposition


def test_reuse_low_speed_ev():
    assert disposition("Second-Life: Low-speed EV", "Low-speed EV")["code"] == "REUSE"
    assert disposition("Second-Life: Low-speed EV", "low_speed_ev")["code"] == "REUSE"


def test_repurpose_stationary_storage():
    assert disposition("Second-Life: Residential solar storage", "residential_storage")["code"] == "REPURPOSE"
    assert disposition("Second-Life: Telecom backup", None)["code"] == "REPURPOSE"


def test_recycle():
    assert disposition("Recycle", None)["code"] == "RECYCLE"
    assert disposition("Reject (safety triage): route to recycling", None)["code"] == "RECYCLE"


def test_inspect():
    assert disposition("Inspection required", None)["code"] == "INSPECT"


def test_no_decision():
    assert disposition("Insufficient or untrustworthy data", None)["code"] == "NO_DECISION"
    out = disposition("something the engine never says", None)
    assert out["code"] == "NO_DECISION" and out["label"]
