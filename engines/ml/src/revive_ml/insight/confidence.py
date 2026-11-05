"""How much to trust a report: a documented HEURISTIC score 0-100 (weights in configs/intelligence.yaml `confidence`).

Factors: data-quality pass fraction, out-of-distribution flag (and chemistry mismatch with the LFP-trained state model),
relative RUL interval width ((upper - lower) / median), gate verdict, telemetry length, data provenance.
It is not a probability and not a calibrated model; the output says so.
"""
from __future__ import annotations

from typing import Any

from revive_ml.config import load
from revive_ml.insight.explain import best_application, val


def _lin(x: float, full: float, zero: float) -> float:
    """1 at or below `full`, 0 at or above `zero`, linear between."""
    if x <= full:
        return 1.0
    if x >= zero:
        return 0.0
    return (zero - x) / (zero - full)


def rul_range(report: dict[str, Any]) -> dict[str, Any] | None:
    r = (report.get("state") or {}).get("rul_cycles_reference")
    if not isinstance(r, dict) or r.get("value") is None:
        return None
    return {"lower": r.get("lower"), "median": r["value"], "upper": r.get("upper"), "unit": "cycles",
            "provenance": "modelled", "nominal_level": r.get("nominal_level"),
            "measured_coverage": r.get("measured_coverage_on_held_out_cells")}


def years_range(report: dict[str, Any]) -> dict[str, Any] | None:
    app = best_application(report)
    pj = (report.get("projections") or {}).get(app) if app else None
    if not pj:
        return None
    y = pj["years_to_application_limit"]
    return {"application": app, "mc_p05": val(y["mc_p05"]), "central": val(y["central"]), "mc_p95": val(y["mc_p95"]),
            "unit": "years", "provenance": "modelled",
            "note": "Monte Carlo band is assumption-conditional (physics-parameter priors), not a measured interval"}


def confidence(report: dict[str, Any], n_rows: int | None = None) -> dict[str, Any]:
    cfg = load("intelligence.yaml")["confidence"]
    model_chem = load("intelligence.yaml").get("insight", {}).get("state_model_chemistry", "LFP")
    w = cfg["weights"]
    factors = []

    rd = (report.get("data_quality") or {}).get("readiness") or {}
    n = rd.get("n_checks") or 0
    frac = (rd.get("n_pass", 0) / n) if n else 0.0
    if rd.get("verdict") == "NOT_READY":
        frac = min(frac, 0.5)
    factors.append(("data_quality", frac, f"{rd.get('n_pass')} of {n} data-quality checks pass ({rd.get('verdict')})"))

    g = report.get("gate") or {}
    ood = (g.get("ood") or {}).get("status")
    ind = {"pass": 1.0, "quarantine": 0.0}.get(ood, 0.5)
    detail = f"out-of-distribution filter: {ood or 'not run'}"
    if report.get("state") and report.get("chemistry") and report["chemistry"] != model_chem:
        ind *= 0.5
        detail += f"; state model trained on {model_chem}, pack is {report['chemistry']}"
    factors.append(("in_distribution", ind, detail))

    rr = rul_range(report)
    if rr and rr["median"] and rr["lower"] is not None and rr["upper"] is not None and rr["median"] > 0:
        width = (rr["upper"] - rr["lower"]) / rr["median"]
        factors.append(("interval_width", _lin(width, cfg["interval_width_full"], cfg["interval_width_zero"]),
                        f"RUL interval width {width:.2f} x the median"))
    else:
        factors.append(("interval_width", 0.0, "no RUL interval (state not estimated)"))

    gv = g.get("verdict")
    factors.append(("gate", cfg["gate_points"].get(gv, 0.0) if gv else 0.0, f"gate verdict: {gv or 'not run'}"))

    if n_rows is None:
        factors.append(("telemetry_length", 0.5, "telemetry length unknown"))
    else:
        factors.append(("telemetry_length", min(1.0, n_rows / cfg["telemetry_rows_full"]), f"{n_rows} telemetry rows"))

    prov = report.get("data_provenance") or "synthetic"
    factors.append(("provenance", cfg["provenance_points"].get(prov, 0.4), f"data provenance: {prov}"))

    rows = [{"factor": k, "points": round(w[k] * x, 2), "max": w[k], "detail": d} for k, x, d in factors]
    score = round(sum(r["points"] for r in rows), 1)
    lv = cfg["levels"]
    level = "High" if score >= lv["High"] else "Medium" if score >= lv["Medium"] else "Low"
    return {"level": level, "score_0_100": score, "factors": rows, "label": cfg.get("label", "heuristic"),
            "rul_range": rr, "years_range": years_range(report)}
