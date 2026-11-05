"""Why this decision: ordered reasons built ONLY from numbers already in the engine report.

Each reason: {stage, tone (good|warn|bad|info), title, text, metric (the report field it cites), provenance, impact}.
`impact` (0-100) ranks reasons by how much they drive the decision; it is a fixed, documented ordering, not a model.
"""
from __future__ import annotations

from typing import Any

from revive_ml.config import load

STAGES = ("data_quality", "gate", "state", "projection", "economics")


def val(x: Any) -> Any:
    return x.get("value") if isinstance(x, dict) else x


def _r(stage, tone, title, text, metric, provenance, impact) -> dict[str, Any]:
    return {"stage": stage, "tone": tone, "title": title, "text": text, "metric": metric,
            "provenance": provenance, "impact": impact}


def best_application(report: dict[str, Any]) -> str | None:
    rec = report.get("recommendation") or {}
    if rec.get("application"):
        return rec["application"]
    opts = (report.get("economics") or {}).get("second_life_options") or {}
    if opts:
        return max(opts, key=lambda k: val(opts[k]["net_value"]))
    proj = report.get("projections") or {}
    return next(iter(proj), None)


def explain(report: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    out: list[dict[str, Any]] = []
    dq = report.get("data_quality") or {}
    rd = dq.get("readiness") or {}
    verdict = rd.get("verdict")
    if verdict:
        tone = {"NOT_READY": "bad", "READY_WITH_WARNINGS": "info", "READY": "good"}.get(verdict, "info")
        out.append(_r("data_quality", tone, f"Data quality: {verdict}",
                      f"{rd.get('n_pass')} of {rd.get('n_checks')} checks pass, {rd.get('n_fail')} fail",
                      "data_quality.readiness", report.get("data_provenance"), 100 if verdict == "NOT_READY" else 10))
    for c in dq.get("checks", []):
        if c["status"] == "fail":
            out.append(_r("data_quality", "bad", f"Check failed: {c['id']}", c["message"],
                          f"data_quality.checks[{c['id']}]", report.get("data_provenance"), 95))
        elif c["status"] in ("warn", "inconclusive"):
            out.append(_r("data_quality", "warn", f"Check {c['status']}: {c['id']}", c["message"],
                          f"data_quality.checks[{c['id']}]", report.get("data_provenance"), 20))

    g = report.get("gate")
    if g:
        v = g.get("verdict")
        if v == "Reject":
            out.append(_r("gate", "bad", "Safety gate: Reject", "; ".join(g.get("reasons", [])), "gate.verdict", "modelled", 92))
        elif v == "Quarantine":
            out.append(_r("gate", "warn", "Safety gate: Quarantine", "; ".join(g.get("reasons", [])), "gate.verdict", "modelled", 85))
        elif v == "Pass":
            out.append(_r("gate", "good", "Safety gate: Pass", "no limit breached, no open high-severity event, "
                          "telemetry inside the healthy-window distribution", "gate.verdict", "modelled", 35))
        ood = g.get("ood") or {}
        if "flagged_fraction" in ood:
            q = ood.get("status") == "quarantine"
            out.append(_r("gate", "warn" if q else "info", "Out-of-distribution filter",
                          f"{ood.get('n_flagged_windows')} of {ood.get('n_windows')} telemetry windows flagged "
                          f"({100 * val(ood['flagged_fraction']):.0f} %)", "gate.ood.flagged_fraction", "modelled", 55 if q else 15))

    st = report.get("state") or {}
    soh = st.get("soh")
    if isinstance(soh, dict) and soh.get("value") is not None:
        s = soh["value"]
        out.append(_r("state", "good" if s >= 80 else "warn" if s >= 60 else "bad", f"State of health {s:.1f} %",
                      soh.get("note") or "", "state.soh", soh.get("provenance"), 60))
    feats = st.get("features") or {}
    if val(feats.get("fade_slope_per_kcycle")) is not None:
        out.append(_r("state", "info", "Fade slope", f"{val(feats['fade_slope_per_kcycle']):.4f} SOH per 1,000 cycles "
                      "(from the capacity-test history)", "state.features.fade_slope_per_kcycle", "modelled", 30))
    ir = val(feats.get("ir_ratio"))
    if ir is not None:
        out.append(_r("state", "warn" if ir > 1.5 else "info", "Resistance growth",
                      f"latest / earliest resistance = {ir:.2f}", "state.features.ir_ratio", "modelled", 40 if ir > 1.5 else 15))
    tmax = val(feats.get("t_max_c"))
    if tmax is not None:
        out.append(_r("state", "warn" if tmax > 45 else "info", "Maximum temperature", f"{tmax:.1f} degC in the telemetry",
                      "state.features.t_max_c", report.get("data_provenance"), 20))
    rul = st.get("rul_cycles_reference")
    if isinstance(rul, dict) and rul.get("value") is not None:
        out.append(_r("state", "info", "Remaining useful life (reference conditions)",
                      f"{rul['value']:.0f} cycles, interval {(rul.get('lower') or 0):.0f}-{(rul.get('upper') or 0):.0f} "
                      f"(nominal {rul.get('nominal_level')}, measured coverage {rul.get('measured_coverage_on_held_out_cells')})",
                      "state.rul_cycles_reference", rul.get("provenance"), 45))
    model_chem = load("intelligence.yaml").get("insight", {}).get("state_model_chemistry", "LFP")
    if st and report.get("chemistry") and report["chemistry"] != model_chem:
        out.append(_r("state", "warn", f"State model trained on {model_chem}, pack is {report['chemistry']}",
                      "the RUL interval's coverage was measured on held-out LFP cells and does not apply to this "
                      "chemistry; treat the remaining-life numbers as indicative", "chemistry", "assumed", 65))
    elif st.get("distribution_shift_note"):
        out.append(_r("state", "info", "Distribution shift", st["distribution_shift_note"],
                      "state.distribution_shift_note", "assumed", 12))

    app = best_application(report)
    pj = (report.get("projections") or {}).get(app) if app else None
    if pj:
        def yrs(x):          # None: the limit is not reached within the projection horizon
            return f"{x:.1f}" if x is not None else "not reached within the projection horizon"
        out.append(_r("projection", "info", f"Years to the {pj['workload']['label']} limit",
                      f"conservative {yrs(val(pj['conservative_years']))} years "
                      f"(central {yrs(val(pj['years_to_application_limit']['central']))})",
                      f"projections.{app}.conservative_years", "modelled", 50))
    econ = report.get("economics")
    if econ:
        opts = econ.get("second_life_options") or {}
        rec_net = val(econ["recycle"]["net_value"])
        if app in opts:
            o = opts[app]
            second = (report.get("decision") or "").startswith("Second-Life")
            out.append(_r("economics", "good" if second else "bad", f"Best second life vs recycling now",
                          f"{o['label']}: net {val(o['net_value']):,.0f} USD vs recycling now {rec_net:,.0f} USD",
                          f"economics.second_life_options.{app}.net_value", "modelled", 90))
            if o.get("capped_by_buy_new"):
                out.append(_r("economics", "warn", "Capped by the buy-new benchmark",
                              f"the energy value is capped at {val(o['buy_new_cap']):,.0f} USD, the cost of new storage "
                              "for the same service", f"economics.second_life_options.{app}.buy_new_cap", "modelled", 50))
        if econ.get("placeholder_inputs"):
            out.append(_r("economics", "info", "Placeholder inputs",
                          f"{len(econ['placeholder_inputs'])} cost/tariff inputs are PLACEHOLDER: "
                          + ", ".join(econ["placeholder_inputs"][:3]) + " ...", "economics.placeholder_inputs", "assumed", 40))
    ranked = sorted(out, key=lambda r: -r["impact"])        # stable: ties keep stage order
    return {"top": ranked[:5], "all": ranked}


def rule_gap(report: dict[str, Any], reasons: dict[str, Any] | None = None) -> dict[str, Any]:
    """The simple SOH rule (state.existing_rule) vs the engine, and why they differ, from the explain reasons."""
    st = report.get("state") or {}
    cmp_ = report.get("comparison_with_existing_rule") or {}
    rule = cmp_.get("existing_rule") or st.get("existing_rule")
    decision = report.get("decision") or ""
    agrees = bool(rule) and rule.split(":")[0] == decision.split(":")[0]
    reasons = reasons or explain(report)
    why = [] if agrees else [f"{r['title']}: {r['text']}" for r in reasons["top"] if r["tone"] in ("bad", "warn")][:3]
    if not agrees and not why:
        why = [f"{r['title']}: {r['text']}" for r in reasons["top"][:2]]
    return {"agrees": agrees, "existing_rule": rule, "engine_decision": decision, "why_different": why,
            "note": "existing rule: SOH > 80 % stationary storage, 60-80 % low-speed EV, < 60 % recycle"}
