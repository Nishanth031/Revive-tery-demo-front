"""Train and evaluate state models on Severson windows. Writes reports/state_metrics.json and
models/state_rul_field.joblib.

Validation: GroupKFold by cell (10 folds) for point metrics; nested GroupKFold (outer 5 x inner 5)
for CV+ interval coverage, so no window of a test cell is ever seen in training or calibration.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import joblib
import numpy as np
import pandas as pd
from mapie.regression import CrossConformalRegressor
from sklearn.base import clone
from sklearn.compose import TransformedTargetRegressor
from sklearn.dummy import DummyRegressor
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import ElasticNet
from sklearn.model_selection import GroupKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from revive_ml.paths import MODELS_DIR, PROCESSED_DIR, REPORTS_DIR
from revive_ml.state.features import FIELD, FULL, SOH_FEATURES

SEED = 0
CONFIDENCE = 0.90
EOL_SOH = 0.80
MAPE_MIN_RUL = 50  # MAPE is undefined near RUL 0; computed on windows with true RUL >= 50
MODEL_PATH = MODELS_DIR / "state_rul_field.joblib"


def _log_target(est: Any) -> TransformedTargetRegressor:
    return TransformedTargetRegressor(regressor=est, func=np.log1p, inverse_func=np.expm1)


def candidates(target: str) -> dict[str, Any]:
    enet = make_pipeline(SimpleImputer(strategy="median"), StandardScaler(),
                         ElasticNet(alpha=0.01, l1_ratio=0.5, max_iter=20_000, random_state=SEED))
    hgb = HistGradientBoostingRegressor(max_iter=300, learning_rate=0.05, max_leaf_nodes=15,
                                        l2_regularization=1.0, random_state=SEED)
    if target == "rul_cycles":
        return {"naive_mean": DummyRegressor(), "elasticnet": _log_target(enet),
                "gradient_boosting": _log_target(hgb)}
    return {"naive_mean": DummyRegressor(), "elasticnet": enet, "gradient_boosting": hgb}


def metrics(y: np.ndarray, p: np.ndarray, target: str) -> dict[str, float]:
    out = {"rmse": float(np.sqrt(np.mean((y - p) ** 2))), "mae": float(np.mean(np.abs(y - p)))}
    if target == "rul_cycles":
        m = y >= MAPE_MIN_RUL
        out["mape_pct"] = float(100 * np.mean(np.abs(y[m] - p[m]) / y[m]))
    else:
        out["mape_pct"] = float(100 * np.mean(np.abs(y - p) / y))
    return out


def oof_predictions(est: Any, X: pd.DataFrame, y: np.ndarray, groups: np.ndarray, k: int = 10) -> np.ndarray:
    p = np.zeros_like(y, dtype=float)
    for tr, te in GroupKFold(n_splits=k).split(X, y, groups):
        m = clone(est).fit(X.iloc[tr], y[tr])
        p[te] = m.predict(X.iloc[te])
    return p


def extrapolation_baseline(X: pd.DataFrame) -> np.ndarray:
    """Engineering baseline: remaining cycles if the window's fade slope continued linearly."""
    slope = np.maximum(X["fade_slope_per_kcycle"].to_numpy() / 1000.0, 1e-5)
    return np.clip((X["soh"].to_numpy() - EOL_SOH) / slope, 0, 5000)


def _tag(v: float, unit: str | None = None) -> dict[str, Any]:
    d: dict[str, Any] = {"value": round(float(v), 4), "provenance": "modelled"}
    if unit:
        d["unit"] = unit
    return d


def evaluate_point(
    df: pd.DataFrame, feats: list[str], target: str
) -> tuple[dict[str, Any], dict[str, np.ndarray]]:
    X, y, g = df[feats], df[target].to_numpy(float), df["cell"].to_numpy()
    res, preds = {}, {}
    for name, est in candidates(target).items():
        p = oof_predictions(est, X, y, g)
        if target == "rul_cycles":
            p = np.clip(p, 0, None)
        preds[name] = p
        res[name] = {k: _tag(v, "cycles" if target == "rul_cycles" and k != "mape_pct" else None)
                     for k, v in metrics(y, p, target).items()}
    if target == "rul_cycles" and "soh" in feats:
        p = extrapolation_baseline(X)
        preds["linear_extrapolation"] = p
        res["linear_extrapolation"] = {k: _tag(v, "cycles" if k != "mape_pct" else None)
                                       for k, v in metrics(y, p, target).items()}
    return res, preds


def conformal(est: Any) -> CrossConformalRegressor:
    return CrossConformalRegressor(clone(est), confidence_level=CONFIDENCE, method="plus",
                                   cv=GroupKFold(n_splits=5), conformity_score="gamma")


def evaluate_intervals(df: pd.DataFrame, feats: list[str], est: Any) -> dict[str, Any]:
    """Nested grouped CV: CV+ is fitted and calibrated on outer-train cells only."""
    X, y, g = df[feats], df["rul_cycles"].to_numpy(float), df["cell"].to_numpy()
    lo, hi, pt = np.zeros_like(y), np.zeros_like(y), np.zeros_like(y)
    for tr, te in GroupKFold(n_splits=5).split(X, y, g):
        m = conformal(est).fit_conformalize(X.iloc[tr], y[tr], groups=g[tr])
        p, pi = m.predict_interval(X.iloc[te])
        pt[te], lo[te], hi[te] = p, np.clip(pi[:, 0, 0], 0, None), pi[:, 1, 0]
    covered = (y >= lo) & (y <= hi)
    by_rul = {}
    for a, b in [(0, 100), (100, 300), (300, 700), (700, 5000)]:
        m = (y >= a) & (y < b)
        by_rul[f"{a}-{b}"] = {"coverage": _tag(covered[m].mean()), "n_windows": int(m.sum())}
    return {
        "method": "CV+ (MAPIE CrossConformalRegressor, method='plus', gamma conformity score), "
                  "inner GroupKFold(5) by cell; outer GroupKFold(5) by cell for measurement",
        "nominal_level": _tag(CONFIDENCE),
        "measured_coverage": _tag(covered.mean()),
        "measured_coverage_by_true_rul": by_rul,
        "median_interval_width": _tag(np.median(hi - lo), "cycles"),
        "note": "Coverage is an empirical measurement on held-out Severson cells. Second-life use "
                "is a distribution shift (different chemistry, pack level, duty), so coverage on "
                "real second-life batteries is unknown.",
        "_arrays": {"y": y, "lo": lo, "hi": hi, "pt": pt},
    }


def rule_comparison(df: pd.DataFrame, iv: dict[str, Any], horizon: int = 365) -> dict[str, Any]:
    """Question: are >= `horizon` cycles left at reference conditions (1 year at 1 cycle/day)?"""
    a = iv["_arrays"]
    truth = a["y"] >= horizon
    rule = df["soh"].to_numpy() > 0.80  # existing rule: SOH > 80 % -> stationary storage
    ml_point = a["pt"] >= horizon
    ml_lower = a["lo"] >= horizon
    out = {"question": f"at least {horizon} cycles remaining at the training protocol's conditions",
           "existing_rule": "SOH > 80 % -> stationary storage; 60-80 % -> low-speed EV; < 60 % -> recycle; "
                            "no measured capacity -> Insufficient data"}
    routes = {"existing_rule": rule, "ml_point": ml_point, "ml_conservative_lower_bound": ml_lower}
    for name, d in routes.items():
        out[name + "_result"] = {
            "accuracy": _tag((d == truth).mean()),
            "false_go_rate": _tag((d & ~truth).sum() / max(1, (~truth).sum())),
            "missed_go_rate": _tag((~d & truth).sum() / max(1, truth.sum())),
        }
    out["note"] = ("All Severson windows are above 80 % SOH by construction, so the existing rule says "
                   "'stationary storage' for every one of them, including cells a few cycles from EOL.")
    return out


@dataclass
class StateModel:
    """Deployed RUL model on FIELD features with CV+ intervals and a training-feature envelope."""

    conformal: CrossConformalRegressor
    features: list[str]
    envelope: dict[str, tuple[float, float]]
    chemistry: str = "LFP"
    reference_conditions: dict[str, Any] = field(default_factory=dict)
    validation: dict[str, Any] = field(default_factory=dict)

    def predict(self, X: pd.DataFrame) -> dict[str, np.ndarray]:
        p, pi = self.conformal.predict_interval(X[self.features])
        return {"point": np.clip(p, 0, None), "lower": np.clip(pi[:, 0, 0], 0, None), "upper": pi[:, 1, 0]}

    def out_of_range(self, X: pd.DataFrame) -> list[str]:
        out = []
        for f in self.features:
            v = X[f].iloc[0]
            lo, hi = self.envelope[f]
            if not np.isfinite(v):
                out.append(f"{f} missing (imputed by the model)")
            elif v < lo or v > hi:
                out.append(f"{f}={v:.4g} outside training range [{lo:.4g}, {hi:.4g}]")
        return out


REFERENCE = {"daily_dod": 1.0, "temperature_c": 30.0, "c_rate": 4.0,
             "note": "Severson protocol: full 2.0-3.6 V cycles in a 30 degC chamber, 4C discharge, "
                     "multi-step fast charge 3.6C-8C. The 4C discharge rate is used as the reference "
                     "C-rate for the physics stress factors."}


def train(write: bool = True) -> dict[str, Any]:
    df = pd.read_parquet(PROCESSED_DIR / "severson_windows.parquet")
    df = df.dropna(subset=["log_var_dq"]).reset_index(drop=True)
    report: dict[str, Any] = {
        "data": {"source": "Severson et al. 2019 (LFP/graphite A123 APR18650M1A), measured",
                 "n_cells": int(df.cell.nunique()), "n_windows": len(df),
                 "window_cycles": 50, "step_cycles": 10, "eol": "80 % of 1.1 Ah nominal",
                 "split": "GroupKFold by cell; windows of one cell never cross train/test"},
        "rul": {}, "soh": {},
    }
    best: dict[str, Any] = {}
    for set_name, feats in {"field": FIELD, "full": FULL}.items():
        res, _ = evaluate_point(df, feats, "rul_cycles")
        report["rul"][set_name] = res
        ml = {k: v for k, v in res.items() if k in ("elasticnet", "gradient_boosting")}
        best[set_name] = min(ml, key=lambda k: ml[k]["rmse"]["value"])
        report["rul"][set_name]["selected"] = best[set_name]
    res, _ = evaluate_point(df, SOH_FEATURES, "soh_target")
    report["soh"]["no_capacity_features"] = res
    report["soh"]["note"] = ("SOH model uses no capacity-derived feature (resistance, temperature, cycle "
                             "count, dQ(V) curve shape). Bundles do not carry dQ(V) curves, so this model "
                             "is reported as a cross-check only; bundle SOH comes from capacity tests.")
    field_est = candidates("rul_cycles")[best["field"]]
    iv = evaluate_intervals(df, FIELD, field_est)
    report["rul"]["field"]["intervals"] = {k: v for k, v in iv.items() if k != "_arrays"}
    report["rule_comparison"] = rule_comparison(df, iv)
    report["gru_lstm"] = ("not attempted: torch is not installed in this environment and the master "
                          "prompt allows a recurrent model only if it beats the baselines; no claim is made "
                          "about whether it would.")
    if write:
        final = conformal(field_est).fit_conformalize(df[FIELD], df["rul_cycles"].to_numpy(float),
                                                      groups=df["cell"].to_numpy())
        env = {f: (float(df[f].quantile(0.01)), float(df[f].quantile(0.99))) for f in FIELD}
        model = StateModel(final, FIELD, env, "LFP", REFERENCE,
                           {"measured_coverage": iv["measured_coverage"]["value"],
                            "nominal_level": CONFIDENCE, "selected": best["field"]})
        MODELS_DIR.mkdir(exist_ok=True)
        joblib.dump(model, MODEL_PATH)
        REPORTS_DIR.mkdir(exist_ok=True)
        (REPORTS_DIR / "state_metrics.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def load_model() -> StateModel | None:
    # joblib uses pickle: only load the file this package wrote itself
    return joblib.load(MODEL_PATH) if MODEL_PATH.exists() else None
