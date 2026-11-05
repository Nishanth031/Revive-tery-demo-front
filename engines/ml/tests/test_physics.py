from __future__ import annotations

import numpy as np
import pytest

from revive_ml.physics.fade import Params, project, stress_factor, trajectory, years_to
from revive_ml.physics.sanity import run as sanity
from revive_ml.provenance import PROJECTED_LABEL, untagged_numbers

REF = {"daily_dod": 1.0, "ambient_c": 30.0, "c_rate": 4.0, "cycles_per_day": 1.0}
RES = {"daily_dod": 0.8, "ambient_c": 25.0, "c_rate": 0.3, "cycles_per_day": 1.0, "min_soh_pct": 60}


def test_reference_conditions_have_unit_stress():
    assert stress_factor(Params.nominal(), REF) == pytest.approx(1.0)


def test_continuity_hits_ml_rul_at_reference():
    years = np.linspace(0, 5, 5 * 365 + 1)
    tr = trajectory(0.93, 500.0, REF, Params.nominal(), years, calendar=False)
    assert tr[0] == pytest.approx(0.93)
    assert years_to(tr, years, 0.80) * 365 == pytest.approx(500.0, rel=0.01)


@pytest.mark.parametrize("key,lo,hi", [("ambient_c", 20, 40), ("c_rate", 0.3, 2.0), ("daily_dod", 0.4, 0.9)])
def test_harsher_workload_ages_faster(key, lo, hi):
    p = Params.nominal()
    assert stress_factor(p, {**RES, key: hi}) > stress_factor(p, {**RES, key: lo})


def test_projection_has_two_separate_bands_and_labels():
    out = project(92.0, {"point": 400.0, "lower": 280.0, "upper": 600.0}, RES, ml_coverage=0.915)
    pt = out["points"][5]
    assert pt["soh"]["note"] == PROJECTED_LABEL
    assert pt["ml_band"]["provenance"] == "modelled" and pt["mc_band"]["provenance"] == "assumed"
    assert pt["ml_band"]["values"][0] <= pt["soh"]["value"] <= pt["ml_band"]["values"][1]
    assert "assumption-conditional" in out["bands"]["monte_carlo"]
    life = out["years_to_application_limit"]
    assert life["ml_conservative"]["value"] <= life["central"]["value"] <= life["ml_optimistic"]["value"]
    assert out["conservative_years"]["value"] <= life["central"]["value"]
    assert untagged_numbers(out) == []


def test_sanity_checks_all_pass():
    r = sanity(write=False)
    assert r["all_pass"], {k: v["pass"] for k, v in r["checks"].items()}
    t = r["checks"]["temperature"]
    assert t["life_ratio_25_vs_45c"] < t["ten_degree_doubling_rule_would_give"]
