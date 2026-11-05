"""Second-use advice: which application suits THIS battery, and why.

The engine's own decision (pipeline.assess) answers "second life, recycle or inspect?". This module adds
the next question for batteries that can go on: "second life where?", using the battery's own
characteristics: its chemistry family and maker (configs/battery_profiles.yaml), its measured health,
and the economics the engine already computed.

Each application gets a fit score in [0, 1] from four parts (weights below):
    health     state of health margin over the application's minimum, resistance growth, open safety events
    chemistry  how well the chemistry family suits the application (ASSUMED priors in battery_profiles.yaml)
    duty       the application's C-rate and cycles/day against what the chemistry tolerates (assumed ceilings)
    economics  the engine's net second-life value per application, scaled between the options (when present)

Honest limits: the chemistry weights and ceilings are literature-style priors, not fitted to second-life
outcomes (none exist in this repository), so the ranking explains and orders options; it does not predict
revenue. The engine's safety gate and data-quality verdict always win: a Reject or a data failure is
never turned into a recommendation.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from revive_ml.config import load
from revive_ml.intelligence.identity import profiles
from revive_ml.provenance import tag

WEIGHTS = {"health": 0.35, "chemistry": 0.30, "duty": 0.15, "economics": 0.20}
HEALTH_MARGIN_FULL = 20.0           # SOH points above an application's minimum that earn a full health score
RESISTANCE_PENALTY_FROM = 1.5       # latest/earliest resistance ratio where a penalty starts
METHOD = ("weighted fit of health, chemistry affinity, duty stress and engine economics; chemistry weights "
          "are assumed priors (configs/battery_profiles.yaml), not fitted to second-life outcomes")


@dataclass
class AdvisorInput:
    chemistry: str
    chemistry_basis: str = "stated"          # user | stated in upload | name in upload | inferred from data | engine
    brand: str | None = None
    soh_pct: float | None = None
    resistance_ratio: float | None = None
    gate: str | None = None                  # Pass | Quarantine | Reject | None
    readiness: str | None = None             # engine data-quality verdict
    open_safety_events: int = 0
    decision: str | None = None              # the engine's own decision text
    economics_options: dict[str, Any] | None = None
    data_provenance: str = "synthetic"


def from_report(report: dict[str, Any], brand: str | None = None, chemistry_basis: str = "engine",
                resistance_ratio: float | None = None) -> AdvisorInput:
    """Read what the advisor needs out of an engine report (nothing in the report is changed)."""
    gate = report.get("gate") or {}
    limits = gate.get("limits") or {}
    soh = ((report.get("state") or {}).get("soh") or {}).get("value")
    if resistance_ratio is None:
        for b in limits.get("breaches", []):
            if b.get("limit") == "resistance_ratio":
                resistance_ratio = (b.get("observed") or {}).get("value")
    econ = report.get("economics") or {}
    return AdvisorInput(
        chemistry=report.get("chemistry") or "", chemistry_basis=chemistry_basis, brand=brand,
        soh_pct=soh, resistance_ratio=resistance_ratio, gate=gate.get("verdict") or (
            "Quarantine" if (gate.get("ood") or {}).get("status") == "quarantine" else None),
        readiness=(report.get("data_quality") or {}).get("readiness", {}).get("verdict"),
        open_safety_events=len(limits.get("open_safety_events", [])),
        decision=report.get("decision"), economics_options=econ.get("second_life_options"),
        data_provenance=report.get("data_provenance", "synthetic"))


def _clip(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def characteristics(chemistry: str, brand: str | None = None) -> dict[str, Any]:
    """The battery family's strengths and cautions, tagged as assumed priors."""
    prof = profiles()
    c = prof["chemistries"].get(chemistry)
    if c is None:
        return {"chemistry": chemistry, "known": False, "note": "no profile for this chemistry"}
    out: dict[str, Any] = {
        "chemistry": chemistry, "known": True, "label": c["label"], "strengths": c["strengths"],
        "cautions": c["cautions"], "scores": {k: tag(v, "assumed", note="qualitative prior, 1 = favourable")
                                              for k, v in c["scores"].items()},
        "provenance": "assumed",
    }
    if brand:
        b = next((x for x in prof["brands"] if x["name"] == brand), None)
        if b:
            out["brand"] = {"name": b["name"], "note": b["note"]}
    return out


def _health(inp: AdvisorInput, min_soh: float) -> tuple[float, list[str], list[str], str | None]:
    reasons: list[str] = []
    cautions: list[str] = []
    if inp.soh_pct is None:
        return 0.0, reasons, cautions, "no state of health is available"
    margin = inp.soh_pct - min_soh
    if margin < 0:
        return 0.0, reasons, cautions, f"state of health {inp.soh_pct:.1f}% is below the {min_soh:.0f}% this application needs"
    score = _clip(margin / HEALTH_MARGIN_FULL)
    reasons.append(f"state of health {inp.soh_pct:.1f}% is {margin:.1f} points above the {min_soh:.0f}% minimum")
    if margin < 5:
        cautions.append("thin health margin: expect to re-test within months")
    if inp.resistance_ratio and inp.resistance_ratio > RESISTANCE_PENALTY_FROM:
        score *= _clip(1 - (inp.resistance_ratio - RESISTANCE_PENALTY_FROM) / 1.5, 0.3, 1.0)
        cautions.append(f"internal resistance has grown {inp.resistance_ratio:.2f}x since the first test")
    if inp.open_safety_events:
        score *= 0.5
        cautions.append(f"{inp.open_safety_events} open safety event(s) must be cleared first")
    return score, reasons, cautions, None


def _duty(w: dict[str, Any], chem: dict[str, Any]) -> tuple[float, list[str], list[str]]:
    reasons, cautions = [], []
    c_max = chem["max_sustained_c_rate"]
    c = float(w.get("c_rate", 0.5))
    c_score = 1.0 if c <= 0.5 * c_max else _clip(1 - (c - 0.5 * c_max) / c_max)
    stress = float(w.get("cycles_per_day", 1.0)) * float(w.get("daily_dod", 0.8))
    s_score = _clip(1 - max(0.0, stress - 0.5 * chem["cycle_stress_ceiling"]) / chem["cycle_stress_ceiling"])
    if c_score < 0.6:
        cautions.append(f"needs {c:.1f}C, high against this chemistry's ~{c_max:.1f}C assumed ceiling")
    else:
        reasons.append(f"{c:.1f}C is comfortable for this chemistry")
    if s_score < 0.6:
        cautions.append(f"{stress:.1f} equivalent full cycles/day is heavy for this chemistry")
    elif stress >= 0.8:
        reasons.append(f"{stress:.1f} equivalent full cycles/day is within what this chemistry tolerates")
    return 0.5 * (c_score + s_score), reasons, cautions


def advise(inp: AdvisorInput, workloads: dict[str, Any] | None = None) -> dict[str, Any]:
    wl = workloads or load("workloads.yaml")["workloads"]
    prof = profiles()
    chem = prof["chemistries"].get(inp.chemistry)
    base: dict[str, Any] = {
        "method": METHOD, "provenance": "modelled",
        "battery": characteristics(inp.chemistry, inp.brand),
        "engine_decision": inp.decision, "gate": inp.gate, "readiness": inp.readiness,
    }
    if chem is None:
        return {**base, "status": "none", "headline": "No suggestion: the chemistry is unknown, so the fit cannot be judged.",
                "suggestions": [], "excluded": []}
    if inp.gate == "Reject" or (inp.decision or "").startswith(("Recycle", "Reject")):
        return {**base, "status": "none",
                "headline": "No second-use suggestion: the engine routes this battery to recycling.",
                "suggestions": [], "excluded": [], "next_step": "recycle"}

    tier = "eligible"
    notes: list[str] = []
    if inp.readiness == "NOT_READY" or (inp.decision or "").startswith("Insufficient"):
        tier = "provisional"
        notes.append("the data failed the engine's quality checks, so health is not trusted: shown for planning only")
    elif inp.gate == "Quarantine" or (inp.decision or "").startswith("Inspection"):
        tier = "provisional"
        notes.append("the engine wants an inspection first: these are the applications to plan for if it passes")

    econ = inp.economics_options or {}
    nets = {k: (o.get("net_value") or {}).get("value") for k, o in econ.items()}
    nets = {k: v for k, v in nets.items() if v is not None}
    lo, hi = (min(nets.values()), max(nets.values())) if nets else (0.0, 0.0)

    rows, excluded = [], []
    for key, w in wl.items():
        label = w.get("label", key)
        min_soh = float(w.get("min_soh_pct", 60))
        h_score, h_reasons, h_cautions, h_block = _health(inp, min_soh)
        aff = chem["affinity"].get(key)
        if h_block:
            excluded.append({"application": key, "label": label, "reason": h_block})
            continue
        c_score = float(aff["fit"]) if aff else 0.5
        d_score, d_reasons, d_cautions = _duty(w, chem)
        parts = {"health": h_score, "chemistry": c_score, "duty": d_score}
        weights = {k: WEIGHTS[k] for k in parts}
        if key in nets:
            parts["economics"] = 1.0 if hi == lo else (nets[key] - lo) / (hi - lo)
            weights["economics"] = WEIGHTS["economics"]
        total = sum(weights.values())
        fit = sum(parts[k] * weights[k] for k in parts) / total
        reasons = [aff["why"]] if aff else []
        reasons += h_reasons + d_reasons
        if key in nets:
            reasons.append(f"engine economics: net {nets[key]:,.0f} USD over a conservative "
                           f"{(econ[key].get('conservative_years') or {}).get('value', 0):.1f} years")
        rows.append({
            "application": key, "label": label, "fit_score": round(fit, 3), "tier": tier,
            "components": {k: round(v, 3) for k, v in parts.items()},
            "reasons": reasons, "cautions": h_cautions + d_cautions,
            "net_value_usd": econ[key].get("net_value") if key in econ else None,
        })
    rows.sort(key=lambda r: -r["fit_score"])
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    if not rows and inp.soh_pct is None:
        return {**base, "status": "none", "next_step": "fix_data", "suggestions": [], "excluded": excluded,
                "headline": "No suggestion yet: the data did not let the engine establish this battery's health. "
                            "Fix what its data-quality checks flagged and re-run.",
                "notes": notes}
    if not rows:
        return {**base, "status": "none", "headline": "No application is served by this battery's current health.",
                "suggestions": [], "excluded": excluded, "next_step": "recycle", "notes": notes}
    top = rows[0]
    headline = (f"Best fit: {top['label']} (fit {top['fit_score']:.2f})" if tier == "eligible"
                else f"Provisional best fit: {top['label']} (fit {top['fit_score']:.2f}), pending the checks above")
    return {**base, "status": "ranked" if tier == "eligible" else "provisional", "headline": headline,
            "suggestions": rows, "excluded": excluded, "notes": notes,
            "confidence": {"chemistry_basis": inp.chemistry_basis,
                           "data_provenance": inp.data_provenance,
                           "weights_are": "assumed priors; see method"}}
