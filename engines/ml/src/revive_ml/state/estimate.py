"""State estimate for a bundle: measured SOH + ML remaining-cycles with CV+ interval.

The ML model was trained on Severson LFP cells (field features only). Its output is turned
into a fade rate at the training protocol's reference conditions, which the physics layer
scales to the user's workload.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from revive_ml.contract import Bundle
from revive_ml.provenance import data_provenance_tag, tag
from revive_ml.state.features import window_row
from revive_ml.state.rules import rule_route

EOL_FRACTION = 0.80


def bundle_field_features(bundle: Bundle, excluded: set[str]) -> pd.DataFrame:
    meta = bundle.meta
    tests = sorted(meta.capacity_tests, key=lambda c: (c.date, c.cycle_count or 0))
    cyc = np.array([t.cycle_count if t.cycle_count is not None else np.nan for t in tests], float)
    soh = np.array([t.measured_capacity_ah / meta.rated_capacity_ah for t in tests])
    rts = sorted(meta.resistance_tests, key=lambda r: (r.date, r.cycle_count or 0))
    ir = np.array([r.resistance_mohm for r in rts], float) if rts and "resistance" not in excluded else None
    ir_first = float(ir[0]) if ir is not None else None
    T = bundle.telemetry["temperature_c"].to_numpy(float)
    k = float(meta.cycle_count or np.nanmax(cyc))
    m = np.isfinite(cyc)
    row = window_row(cyc[m], soh[m], ir, ir_first, T, T, k)
    # capacity and resistance tests are sparse: use the latest record, not a 5-point median
    row["soh"] = float(soh[-1])
    if ir is not None:
        row["ir_ratio"] = float(ir[-1] / ir_first)
    return pd.DataFrame([row])


def estimate(bundle: Bundle, model: Any | None = None, excluded: set[str] | None = None) -> dict[str, Any]:
    from revive_ml.state.train import load_model

    meta = bundle.meta
    excluded = excluded or set()
    tests = sorted(meta.capacity_tests, key=lambda c: (c.date, c.cycle_count or 0))
    if not tests:
        return {"status": "insufficient", "reason": "no measured capacity: SOH cannot be anchored",
                "existing_rule": rule_route(None)}
    prov = data_provenance_tag(tests[-1].provenance)
    soh = tests[-1].measured_capacity_ah / meta.rated_capacity_ah
    out: dict[str, Any] = {
        "status": "ok",
        "soh": tag(100 * soh, prov, "%", note=f"latest capacity test {tests[-1].date} / rated capacity"),
        "existing_rule": rule_route(100 * soh),
        "warnings": [],
    }
    model = model or load_model()
    X = bundle_field_features(bundle, excluded)
    out["features"] = {k: tag(float(v) if np.isfinite(v) else None, prov) for k, v in X.iloc[0].items()}
    if "resistance" in excluded:
        out["warnings"].append("resistance excluded (data-quality check inconclusive); model imputes it")
    if soh <= EOL_FRACTION:
        out["warnings"].append("SOH at or below 80 %: below the ML training range; fade rate from the "
                               "capacity-test trend only")
        out.update(_trend_fallback(X, soh))
        return out
    if model is None:
        out["warnings"].append("no trained state model (run `revive-ml train`); using capacity-test trend")
        out.update(_trend_fallback(X, soh))
        return out
    pred = model.predict(X)
    point, lo, hi = float(pred["point"][0]), float(pred["lower"][0]), float(pred["upper"][0])
    cov = model.validation.get("measured_coverage")
    out["method"] = (f"{model.validation.get('selected')} on field features, trained on Severson LFP "
                     "cells; CV+ interval")
    out["rul_cycles_reference"] = tag(point, "modelled", "cycles",
                                      note="remaining cycles to 80 % SOH at the training conditions",
                                      lower=round(lo, 1), upper=round(hi, 1),
                                      nominal_level=model.validation.get("nominal_level"),
                                      measured_coverage_on_held_out_cells=cov)
    span = soh - EOL_FRACTION
    out["fade_rate_ref"] = tag(span / max(point, 1.0), "modelled", "SOH fraction per reference cycle",
                               note="(SOH - 0.80) / predicted RUL; the ML-to-physics hand-over")
    out["fade_rate_ref_conservative"] = tag(span / max(lo, 1.0), "modelled",
                                            "SOH fraction per reference cycle",
                                            note="from the CV+ lower bound of RUL (conservative)")
    out["fade_rate_ref_optimistic"] = tag(span / max(hi, 1.0), "modelled", "SOH fraction per reference cycle")
    out["reference_conditions"] = {"provenance": "assumed", "values": model.reference_conditions}
    oor = model.out_of_range(X)
    if meta.chemistry != model.chemistry:
        out["warnings"].append(f"chemistry out of distribution: model trained on {model.chemistry}, "
                               f"battery is {meta.chemistry}; the interval's coverage does not apply")
    if oor:
        out["warnings"].append("inputs outside the training feature distribution: " + "; ".join(oor))
    out["out_of_distribution"] = bool(oor) or meta.chemistry != model.chemistry
    out["distribution_shift_note"] = ("Second-life packs differ from the Severson training cells "
                                      "(pack level, duty, often chemistry). Interval coverage was measured "
                                      "on held-out Severson cells only.")
    return out


def _trend_fallback(X: pd.DataFrame, soh: float) -> dict[str, Any]:
    slope = max(float(X["fade_slope_per_kcycle"].iloc[0]) / 1000.0, 1e-6)
    return {"method": "linear capacity-test trend (fallback, not ML)",
            "fade_rate_ref": tag(slope, "modelled", "SOH fraction per cycle",
                                 note="slope of capacity tests; observed duty, not reference conditions"),
            "fade_rate_ref_conservative": tag(1.5 * slope, "modelled", "SOH fraction per cycle",
                                              note="1.5x trend slope (assumed margin)"),
            "fade_rate_ref_optimistic": tag(slope / 1.5, "modelled", "SOH fraction per cycle"),
            "out_of_distribution": True}
