from __future__ import annotations

import numpy as np
import pytest

from revive_ml import gate
from revive_ml.contract import SafetyEvent
from revive_ml.dq.inject import _copy
from revive_ml.gate.ood import load_default
from revive_ml.pipeline import INSPECTION, assess
from revive_ml.synth import NMC_SPEC, make_clean_bundle

needs_model = pytest.mark.skipif(load_default() is None, reason="run `revive-ml train-gate` first")


def test_wording_is_triage_not_certification(clean_bundle):
    g = gate.evaluate(clean_bundle)
    assert "UL 1974-style triage" in g["wording"]
    assert "not UL certification" in g["wording"]


@pytest.mark.parametrize("spec,v_cell", [(None, 1.9), (NMC_SPEC, 2.7)], ids=["LFP<2.0V", "NMC<2.75V"])
def test_undervoltage_rejects(spec, v_cell):
    b = make_clean_bundle(spec) if spec else make_clean_bundle()
    b.telemetry.loc[100, "voltage_v"] = v_cell * b.meta.series_cells
    g = gate.evaluate(b)
    assert g["verdict"] == "Reject"
    assert g["limits"]["breaches"][0]["limit"] == "cell_v_min"
    assert g["limits"]["breaches"][0]["threshold"]["provenance"] == "assumed"


def test_overtemperature_rejects(clean_bundle):
    clean_bundle.telemetry.loc[50, "temperature_c"] = 72.0
    assert gate.evaluate(clean_bundle)["verdict"] == "Reject"


def test_resistance_doubling_rejects(clean_bundle):
    b = _copy(clean_bundle)
    rt = b.meta.resistance_tests
    rt[-1] = rt[-1].model_copy(update={"resistance_mohm": rt[0].resistance_mohm * 2.1})
    assert gate.evaluate(b)["verdict"] == "Reject"


@needs_model
def test_open_high_severity_event_quarantines(clean_bundle):
    b = _copy(clean_bundle)
    b.meta.safety_events = [SafetyEvent(timestamp_utc="2026-10-01T00:00:00Z", event_type="THERMAL",
                                        severity="HIGH", status="OPEN", provenance="synthetic")]
    g = gate.evaluate(b)
    assert g["verdict"] == "Quarantine"


@needs_model
@pytest.mark.parametrize("seed", [11, 12, 13])
def test_clean_pack_passes_ood(seed):
    g = gate.evaluate(make_clean_bundle(seed=seed))
    assert g["verdict"] == "Pass", g["ood"]
    assert g["ood"]["model_family"] == "synthetic_packs"
    assert g["ood"]["training_provenance"] == "synthetic"


@needs_model
def test_spiky_pack_is_quarantined_and_report_says_inspection(clean_bundle):
    b = _copy(clean_bundle)
    rng = np.random.default_rng(0)
    for k in rng.choice(len(b.telemetry), 4, replace=False):
        b.telemetry.loc[k, "voltage_v"] += 0.3 * b.meta.series_cells
    g = gate.evaluate(b)
    assert g["verdict"] == "Quarantine" and g["ood"]["status"] == "quarantine"
    r = assess(b)
    # spikes this large are also a data-quality fault; either way no recommendation is made
    assert r["recommendation"] is None
    assert r["decision"] in (INSPECTION, "Insufficient or untrustworthy data")
