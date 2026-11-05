"""revive_ml.insight (P2): explain, confidence, what-if/break-even/robustness, fleet plan, passport, reuse valuation."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from revive_ml.contract import load_bundle
from revive_ml.insight import (assess_with_insight, assign, break_even, confidence, explain, impact, insight_for,
                               next_best_actions, passport, reroute, robustness, rule_gap, scale)
from revive_ml.paths import REPO_ROOT
from revive_ml.pipeline import assess
from revive_ml.synth import NMC_SPEC, make_clean_bundle

CONTRACTS = Path(__file__).resolve().parents[3] / "contracts"


@pytest.fixture(scope="module")
def clean():
    lfp = load_bundle(REPO_ROOT / "examples" / "clean_synthetic_bundle")
    nmc = make_clean_bundle(NMC_SPEC, seed=3)
    return {"lfp": (lfp, assess(lfp)), "nmc": (nmc, assess(nmc))}


def _resolve(report, metric):
    """Follow a reason's `metric` path through the report; True when the field exists."""
    if metric == "chemistry":
        return "chemistry" in report
    cur = report
    for part in metric.replace("]", "").split("."):
        name, _, key = part.partition("[")
        cur = cur.get(name) if isinstance(cur, dict) else None
        if cur is None:
            return False
        if key:
            cur = next((c for c in cur if c.get("id") == key), None)
            if cur is None:
                return False
    return True


def test_explain_cites_only_existing_fields(clean):
    for _, r in clean.values():
        e = explain(r)
        assert 1 <= len(e["top"]) <= 5 and len(e["all"]) >= len(e["top"])
        for reason in e["all"]:
            assert _resolve(r, reason["metric"]), reason
            assert reason["tone"] in ("good", "warn", "bad", "info") and reason["stage"]
    nmc = explain(clean["nmc"][1])
    assert any("trained on LFP" in x["title"] and x["tone"] == "warn" for x in nmc["all"])       # P2.10 prominence


def test_confidence_is_bounded_and_drops_when_data_quality_fails(clean):
    b, r = clean["lfp"]
    good = confidence(r, len(b.telemetry))
    assert 0 <= good["score_0_100"] <= 100 and good["label"] == "heuristic"
    bad = copy.deepcopy(r)
    bad["data_quality"]["readiness"].update({"verdict": "NOT_READY", "n_pass": 5, "n_fail": 9})
    bad["gate"] = None
    assert confidence(bad, len(b.telemetry))["score_0_100"] < good["score_0_100"]
    assert good["rul_range"]["lower"] < good["rul_range"]["median"] < good["rul_range"]["upper"]
    assert good["years_range"]["mc_p05"] <= good["years_range"]["central"] <= good["years_range"]["mc_p95"]


def test_break_even_finds_the_known_tariff_flip_on_the_clean_packs(clean):
    for _, r in clean.values():
        be = break_even(r, "tariff")
        assert be and 0.06 <= be["value"] <= 0.08, be
        assert {be["below"], be["above"]} == {"Recycle", "Second-Life"} and be["evaluations"] <= 40
        assert reroute(r, {"tariff": be["value"] - 0.002})["decision"].split(":")[0] == be["below"]
        assert reroute(r, {"tariff": be["value"] + 0.002})["decision"].split(":")[0] == be["above"]


def test_reroute_with_no_overrides_reproduces_the_engine_decision(clean):
    for _, r in clean.values():
        assert reroute(r)["decision"] == r["decision"]


def test_robustness_share_is_a_fraction(clean):
    rob = robustness(clean["lfp"][1])
    assert 0 <= rob["share_same_decision"] <= 1 and rob["scenarios"] > 1
    assert rob["break_even_tariff"] is not None and isinstance(rob["flips"], list)


def test_region_default_unchanged_and_sourced_region_changes_the_tariff(clean):
    b, r = clean["lfp"]
    assert assess(b, region="global_default")["decision"] == r["decision"]
    us = assess(b, region="us_residential_avoided_purchase")
    assert us["economics"]["region"] == "us_residential_avoided_purchase"
    with pytest.raises(ValueError):
        assess(b, region="atlantis")


def test_low_speed_ev_is_valued_as_an_avoided_new_pack(clean):
    o = clean["lfp"][1]["economics"]["second_life_options"]["low_speed_ev"]
    assert o["valuation_mode"] == "avoided_new_pack" and o["capped_by_buy_new"] is False
    assert o["buy_new_cap"]["value"] is None
    assert clean["lfp"][1]["economics"]["second_life_options"]["residential_storage"]["valuation_mode"] == "energy_arbitrage"


def test_fleet_assignment_never_exceeds_limits_and_never_loses_to_greedy():
    packs = [{"asset_id": f"P{i}", "eligible": i % 5 != 0, "kwh": 10 + i,
              "options": {"residential_storage": 100 + 7 * i, "commercial_peak_shaving": 140 - 3 * i, "low_speed_ev": 50 + (i % 3) * 40},
              "recycle": 20} for i in range(15)]
    limits = {"residential_storage": {"packs": 4}, "commercial_peak_shaving": {"packs": 3, "kwh": 45}, "low_speed_ev": {"packs": 2}}
    out = assign(packs, limits)
    for a, lim in limits.items():
        chosen = [p for p in packs if any(x["asset_id"] == p["asset_id"] and x["application"] == a for x in out["plan"])]
        assert len(chosen) <= lim["packs"]
        if "kwh" in lim:
            assert sum(p["kwh"] for p in chosen) <= lim["kwh"] + 1e-9
    ineligible = {p["asset_id"] for p in packs if not p["eligible"]}
    assert not ineligible & {x["asset_id"] for x in out["plan"]}
    assert out["total_value"] >= out["greedy_value"] - 1e-9
    assert out["value_gap_vs_per_pack_greedy"] >= -1e-9
    exact = assign(packs, {"residential_storage": {"packs": 4}, "low_speed_ev": {"packs": 2}})
    assert exact["exact_total"] is None or exact["total_value"] <= exact["exact_total"] + 1e-6


def test_impact_and_scale_are_tagged(clean):
    packs = [{"disposition": "REPURPOSE", "net_value": 100.0, "recycle_value": 10.0, "pack_kwh": 50.0, "soh": 90.0},
             {"disposition": "RECYCLE", "net_value": None, "recycle_value": 30.0, "pack_kwh": 40.0, "soh": 70.0}]
    imp = impact(packs)
    assert imp["kwh_redeployed"]["value"] == 45.0 and imp["kwh_redeployed"]["provenance"] == "modelled"
    assert imp["value_vs_recycle_all"]["value"] == pytest.approx(130.0 - 40.0)
    s = scale(imp, 200)
    assert s["n_packs"]["provenance"] == "assumed" and s["assumptions"]


def _validate(value, schema, where="$"):
    errs = []
    t = schema.get("type")
    types = t if isinstance(t, list) else [t] if t else []
    py = {"object": dict, "array": list, "string": str, "number": (int, float), "integer": int, "null": type(None), "boolean": bool}
    if types and not any(isinstance(value, py[x]) for x in types):
        errs.append(f"{where}: {type(value).__name__} not {types}")
    if "enum" in schema and value not in schema["enum"]:
        errs.append(f"{where}: {value!r} not in enum")
    if isinstance(value, dict):
        errs += [f"{where}.{k}: missing" for k in schema.get("required", []) if k not in value]
        for k, sub in schema.get("properties", {}).items():
            if k in value:
                errs += _validate(value[k], sub, f"{where}.{k}")
    if isinstance(value, list) and "items" in schema:
        for i, x in enumerate(value):
            errs += _validate(x, schema["items"], f"{where}[{i}]")
    return errs


def test_passport_validates_against_its_schema(clean):
    b, r = clean["lfp"]
    pp = passport(r, b.meta, b.telemetry, {"code": "REPURPOSE", "label": "Repurpose"})
    schema = json.loads((CONTRACTS / "battery_passport.schema.json").read_text(encoding="utf-8"))
    assert _validate(json.loads(json.dumps(pp, default=str)), schema) == []
    assert pp["note"] == "informational, not a regulatory document" and len(pp["input_telemetry_sha256"]) == 64


def test_assess_with_insight_is_additive_and_schema_valid(clean):
    b, r = clean["nmc"]
    out = assess_with_insight(b)
    for k in r:
        if k != "generated_utc":
            assert out[k] == r[k], k
    schema = json.loads((CONTRACTS / "assessment_report.schema.json").read_text(encoding="utf-8"))
    assert _validate(json.loads(json.dumps(out, default=str)), schema) == []
    assert out["insight"]["rule_gap"]["existing_rule"] and out["insight"]["next_actions"]
    acts = next_best_actions(r, ["chemistry"])
    assert acts[0]["action"].startswith("Supply") and any("tariff" in a["action"] for a in acts)
    assert rule_gap(r)["agrees"] in (True, False)
    assert insight_for(r, b, with_robustness=False)["robustness"] is None


def test_explain_handles_a_limit_that_is_never_reached_and_missing_rul_bounds(clean):
    r = copy.deepcopy(clean["lfp"][1])
    app = r["recommendation"]["application"]
    r["projections"][app]["years_to_application_limit"]["central"]["value"] = None
    r["state"]["rul_cycles_reference"]["lower"] = None
    texts = " ".join(x["text"] for x in explain(r)["all"])
    assert "not reached within the projection horizon" in texts
    assert next_best_actions(r)                     # no crash on the missing bound
