from __future__ import annotations

import numpy as np
import pytest

from revive_ml.dq.detectors import run_all
from revive_ml.dq.inject import FAULTS
from revive_ml.dq.readiness import readiness
from revive_ml.synth import NMC_SPEC, PackSpec, make_clean_bundle


def _by_id(bundle):
    return {c.id: c for c in run_all(bundle)}


# ---------------------------------------------------------------- demo data: the known defects
def test_demo_sign_convention_inferred_and_power_conflict(demo_bundle):
    c = _by_id(demo_bundle)["sign_convention"]
    assert c.status == "warn"
    assert c.evidence["inferred"] == "discharge_negative"
    assert c.evidence["power_column_convention"] == "discharge_positive"
    assert c.evidence["data_flipped"] is False


def test_demo_charge_balance_mismatch(demo_bundle):
    c = _by_id(demo_bundle)["charge_balance"]
    assert c.status == "fail"
    assert c.evidence["recorded_soc_span"]["value"] == pytest.approx(34.0)
    # trapezoid on 300 s steps: 33.17 Ah -> 17.1 points of the 193.6 Ah test capacity
    assert c.evidence["coulomb_counted_throughput_ah"]["value"] == pytest.approx(33.17, abs=0.01)
    assert c.evidence["soc_points_explained_by_current"]["value"] == pytest.approx(17.13, abs=0.05)
    assert c.evidence["coulomb_counted_throughput_ah"]["provenance"] == "synthetic"


def test_demo_regen_wrong_sign(demo_bundle):
    c = _by_id(demo_bundle)["regen_sign"]
    assert c.status == "fail" and c.evidence["wrong_sign_rows"] == 1
    assert c.evidence["first_rows"] == [3]


def test_demo_resistance_inconclusive_not_pass(demo_bundle):
    c = _by_id(demo_bundle)["resistance"]
    assert c.status == "inconclusive"
    assert c.evidence["per_cell_resistance"]["value"] == pytest.approx(2.2 * 40 / 96, rel=1e-3)
    assert c.evidence["resistance_based_soh_clipped"]["value"] == 100.0


def test_demo_estimate_disagreement_reports_both(demo_bundle):
    c = _by_id(demo_bundle)["estimate_disagreement"]
    assert c.status == "fail"
    assert c.evidence["soh_from_capacity_test"]["value"] == pytest.approx(96.8)
    assert 45 < c.evidence["live_soh_from_telemetry"]["value"] < 55
    assert c.evidence["decision_trusts"] == "capacity test"
    assert "charge-balance check failed" in c.evidence["why"]


def test_demo_timestamps_are_regular(demo_bundle):
    c = _by_id(demo_bundle)["timestamps"]
    assert c.status == "pass" and c.evidence["median_step"]["value"] == 300


def test_demo_not_ready_by_rule_r1(demo_bundle):
    r = readiness(run_all(demo_bundle))
    assert r["verdict"] == "NOT_READY" and r["rule_applied"].startswith("R1")
    assert set(r["triggering_checks"]) == {"charge_balance", "regen_sign", "estimate_disagreement"}
    assert "resistance" in r["excluded_from_decision"]


def test_detectors_never_modify_input(demo_bundle):
    before = demo_bundle.telemetry.copy()
    run_all(demo_bundle)
    assert demo_bundle.telemetry.equals(before)


# ---------------------------------------------------------------- clean data and injected faults
@pytest.mark.parametrize("spec", [PackSpec(), NMC_SPEC], ids=["LFP", "NMC"])
def test_clean_bundle_only_provenance_warns(spec):
    checks = run_all(make_clean_bundle(spec, seed=7))
    flagged = {c.id: c.status for c in checks if c.status not in ("pass", "not_applicable")}
    assert flagged == {"provenance": "warn"}
    assert readiness(checks)["verdict"] == "READY_WITH_WARNINGS"


@pytest.mark.parametrize("fault", sorted(FAULTS))
@pytest.mark.parametrize("spec", [PackSpec(), NMC_SPEC], ids=["LFP", "NMC"])
def test_each_injected_fault_is_detected(fault, spec):
    inject, detector, statuses = FAULTS[fault]
    clean = make_clean_bundle(spec, seed=3)
    faulty = inject(clean, np.random.default_rng(3))
    res = _by_id(faulty)[detector]
    assert res.status in statuses, (fault, res.status, res.message)
    assert _by_id(clean)[detector].status in ("pass", "not_applicable", "warn")


def test_integration_uses_row_to_row_step():
    """Removing every other row in one half must not change the coulomb count much."""
    b = make_clean_bundle(seed=1)
    full = _by_id(b)["charge_balance"].evidence["coulomb_counted_throughput_ah"]["value"]
    df = b.telemetry
    keep = np.ones(len(df), bool)
    keep[: len(df) // 2 : 2] = False
    b.telemetry = df[keep].reset_index(drop=True)
    thinned = _by_id(b)["charge_balance"].evidence["coulomb_counted_throughput_ah"]["value"]
    assert thinned == pytest.approx(full, rel=0.02)
