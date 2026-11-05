"""Out-of-distribution and sensor-noise filter (gate stage b).

An IsolationForest trained on HEALTHY windows only. It flags telemetry that does not look
like the healthy windows it has seen: sensor noise, spikes, dropouts, unusual operating
regimes. It is NOT a fault detector and a low score is not a diagnosis; it sends the
battery to inspection.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import FunctionTransformer, StandardScaler

from revive_ml.config import load
from revive_ml.contract import Bundle
from revive_ml.gate.features import FEATURES, MIN_ROWS, window_features
from revive_ml.paths import MODELS_DIR
from revive_ml.provenance import tag

# Two model families. Cell-level lab data and pack drive-cycle data look nothing alike; one forest
# trained on both was too loose for packs and too strict for unseen cells (see PLAN.md D8).
MODEL_PATHS = {
    "measured_cells": MODELS_DIR / "gate_ood_measured_cells.joblib",  # NASA PCoE, measured
    "synthetic_packs": MODELS_DIR / "gate_ood_synthetic_packs.joblib",  # revive_ml.synth, synthetic
}
LOG_FEATURES = ["resid_mad_mv", "resid_max_z", "temp_resid_z", "c_rate_rms"]
# Bundle rule: quarantine when more than 10 % of windows score below the 1st-percentile
# training score, or when 2+ windows fall outside the training envelope. The envelope exists
# because an IsolationForest saturates: a point far beyond the training range is isolated no
# faster than the most extreme training point, so gross spikes and dropouts can score only
# moderately. Envelope = [q0.1 - 3*w, q99.9 + 3*w] per (transformed) feature, w = q99.9 - q0.1.
FLAG_FRACTION = 0.10
ENVELOPE_WINDOWS = 2
ENVELOPE_MARGIN = 3.0


def _log_some(X: pd.DataFrame) -> pd.DataFrame:
    X = X.copy()
    for c in LOG_FEATURES:
        X[c] = np.log1p(np.abs(X[c]))
    X["resid_mean_t"] = np.sign(X["resid_mean_t"]) * np.log1p(np.abs(X["resid_mean_t"]))
    return X


def chemistry_window(chemistry: str) -> tuple[float, float]:
    lim = load("limits.yaml")["chemistries"][chemistry]
    return lim["cell_v_min"]["value"], lim["cell_v_max"]["value"]


def bundle_features(bundle: Bundle, convention: str | None = None) -> pd.DataFrame:
    from revive_ml.dq.detectors import build_context, seconds

    meta = bundle.meta
    ctx = build_context(bundle)
    conv = convention or ctx.convention
    df = ctx.df
    sign = 1.0 if conv == "discharge_negative" else -1.0
    series = meta.series_cells or 1
    vmin, vmax = chemistry_window(meta.chemistry)
    return window_features(
        df["voltage_v"].to_numpy(float) / series,
        sign * df["current_a"].to_numpy(float) / meta.rated_capacity_ah,
        df["temperature_c"].to_numpy(float),
        seconds(df["timestamp_utc"]),
        vmin, vmax,
    )


@dataclass
class OODFilter:
    pipeline: Pipeline
    thr_flag: float
    env_lo: np.ndarray
    env_hi: np.ndarray
    training_summary: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def fit(cls, X: pd.DataFrame, seed: int = 0, summary: dict[str, Any] | None = None) -> OODFilter:
        pipe = Pipeline([
            ("log", FunctionTransformer(_log_some)),
            ("scale", StandardScaler()),
            ("iforest", IsolationForest(n_estimators=300, random_state=seed)),
        ])
        pipe.fit(X[FEATURES])
        s = pipe.score_samples(X[FEATURES])
        Z = _log_some(X[FEATURES]).to_numpy()
        q_lo, q_hi = np.quantile(Z, 0.001, axis=0), np.quantile(Z, 0.999, axis=0)
        w = np.maximum(q_hi - q_lo, 1e-6)
        return cls(pipe, float(np.quantile(s, 0.01)), q_lo - ENVELOPE_MARGIN * w,
                   q_hi + ENVELOPE_MARGIN * w, summary or {})

    def score(self, X: pd.DataFrame) -> np.ndarray:
        return self.pipeline.score_samples(X[FEATURES])

    def outside_envelope(self, X: pd.DataFrame) -> np.ndarray:
        Z = _log_some(X[FEATURES]).to_numpy()
        return ((self.env_lo > Z) | (self.env_hi < Z)).any(axis=1)

    def decide(self, X: pd.DataFrame) -> dict[str, Any]:
        if len(X) == 0:
            return {"status": "unavailable", "note": f"fewer than {MIN_ROWS} rows; no window to score"}
        s = self.score(X)
        flagged = s < self.thr_flag
        outside = self.outside_envelope(X)
        frac = float(flagged.mean())
        quarantine = frac > FLAG_FRACTION or int(outside.sum()) >= ENVELOPE_WINDOWS
        out = {
            "status": "quarantine" if quarantine else "pass",
            "n_windows": len(X),
            "n_flagged_windows": int(flagged.sum()),
            "n_outside_envelope_windows": int(outside.sum()),
            "flagged_fraction": tag(frac, "modelled"),
            "rule": f"quarantine if IsolationForest flags > {FLAG_FRACTION:.0%} of windows or >= "
                    f"{ENVELOPE_WINDOWS} windows fall outside the training envelope",
            "description": "IsolationForest trained on healthy windows: an out-of-distribution and "
                           "sensor-noise filter, not a fault detector",
        }
        if quarantine:
            worst = X.iloc[int(np.argmin(s))]
            out["reason"] = (f"telemetry outside the healthy-window distribution "
                             f"({flagged.sum()} of {len(X)} windows flagged)")
            out["most_unusual_window"] = {k: tag(float(worst[k]), "modelled") for k in FEATURES}
        return out

    def assess(self, bundle: Bundle) -> dict[str, Any]:
        X = bundle_features(bundle)
        out = self.decide(X)
        out["model_family"] = self.training_summary.get("family", "unknown")
        out["trained_on"] = self.training_summary.get("trained_on", "unknown")
        out["training_provenance"] = self.training_summary.get("provenance", "unknown")
        return out

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(self, path)


def family_for(bundle: Bundle) -> str:
    """Packs (more than one cell) use the pack model; single cells use the measured-cell model."""
    m = bundle.meta
    is_pack = (m.series_cells or 1) > 1 or (m.parallel_cells or 1) > 1
    return "synthetic_packs" if is_pack else "measured_cells"


def load_default(family: str = "synthetic_packs") -> OODFilter | None:
    path = MODEL_PATHS[family]
    # joblib uses pickle: only ever load the file this package wrote itself
    return joblib.load(path) if path.exists() else None
