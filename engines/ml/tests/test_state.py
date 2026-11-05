from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest
from sklearn.linear_model import LinearRegression

from revive_ml.contract import Metadata
from revive_ml.dq.inject import _copy
from revive_ml.paths import REPORTS_DIR
from revive_ml.state import train as st_train
from revive_ml.state.estimate import estimate
from revive_ml.state.rules import rule_route
from revive_ml.state.train import load_model

needs_model = pytest.mark.skipif(load_model() is None, reason="run `revive-ml train` first")


@pytest.mark.parametrize("soh,route", [(None, "Insufficient data"), (85, "Second-Life: stationary storage"),
                                       (80, "Second-Life: low-speed EV"), (60, "Second-Life: low-speed EV"),
                                       (59.9, "Recycle")])
def test_existing_rule(soh, route):
    assert rule_route(soh) == route


def test_grouped_oof_never_leaks_cells(monkeypatch):
    """Every fitted model must be trained on cells disjoint from the cells it predicts."""
    seen = []

    class Spy(LinearRegression):
        def fit(self, X, y):
            seen.append(set(X["cell_id"]))
            return super().fit(X, y)

    rng = np.random.default_rng(0)
    X = pd.DataFrame({"cell_id": np.repeat(np.arange(20), 5), "x": rng.normal(size=100)})
    y = X["x"].to_numpy() * 2
    st_train.oof_predictions(Spy(), X, y, X["cell_id"].to_numpy(), k=5)
    for train_cells in seen:
        assert len(train_cells) == 16  # 4 of 20 cells held out per fold, never mixed


def test_no_capacity_test_is_insufficient(clean_bundle):
    b = _copy(clean_bundle)
    b.meta = Metadata.model_validate({**b.meta.model_dump(), "capacity_tests": []})
    r = estimate(b)
    assert r["status"] == "insufficient" and r["existing_rule"] == "Insufficient data"


@needs_model
def test_lfp_clean_bundle_gets_interval_and_fade_rate(clean_bundle):
    r = estimate(clean_bundle)
    rul = r["rul_cycles_reference"]
    assert rul["provenance"] == "modelled"
    assert rul["lower"] <= rul["value"] <= rul["upper"]
    assert r["fade_rate_ref_conservative"]["value"] >= r["fade_rate_ref"]["value"]
    assert 0.8 <= rul["measured_coverage_on_held_out_cells"] <= 1.0
    assert r["soh"]["provenance"] == "synthetic"


@needs_model
def test_nmc_pack_gets_chemistry_ood_warning(demo_bundle):
    r = estimate(demo_bundle, excluded={"resistance"})
    assert r["out_of_distribution"] is True
    assert any("chemistry out of distribution" in w for w in r["warnings"])
    assert any("resistance excluded" in w for w in r["warnings"])
    assert r["features"]["ir_ratio"]["value"] is None


@pytest.mark.skipif(not (REPORTS_DIR / "state_metrics.json").exists(), reason="no metrics report")
def test_metrics_report_beats_naive_and_reports_measured_coverage():
    r = json.loads((REPORTS_DIR / "state_metrics.json").read_text())
    for s in ("field", "full"):
        res = r["rul"][s]
        assert res[res["selected"]]["rmse"]["value"] < res["naive_mean"]["rmse"]["value"]
    iv = r["rul"]["field"]["intervals"]
    assert "measured_coverage" in iv and "guaranteed" not in json.dumps(r).lower()
