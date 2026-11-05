from __future__ import annotations

import pytest
import yaml

from revive_ml.config import load
from revive_ml.econ.router import recycle_value, second_life_value
from revive_ml.econ.sensitivity import sweep
from revive_ml.paths import config_path
from revive_ml.pipeline import assess

W = {"daily_dod": 0.8, "cycles_per_day": 1.0}


def test_every_price_has_status_and_sourced_ones_have_url_and_date():
    cfg = yaml.safe_load(config_path("economics.yaml").read_text())

    def walk(d, path=""):
        if isinstance(d, dict):
            if "value" in d and isinstance(d["value"], int | float):
                assert d.get("status") in ("sourced", "assumed", "PLACEHOLDER"), path
                if d["status"] == "sourced":
                    assert d.get("url") and d.get("retrieved"), path
            for k, v in d.items():
                walk(v, f"{path}.{k}")

    walk(cfg)


def test_recycle_value_scales_with_metal_prices():
    base = recycle_value("NMC", 60.0)["net_usd"]
    high = recycle_value("NMC", 60.0, mult={"nickel": 2, "cobalt": 2, "lithium": 2})["net_usd"]
    assert high > base
    lfp = recycle_value("LFP", 60.0)
    assert lfp["nickel_usd"] == 0 and lfp["cobalt_usd"] == 0


def test_second_life_capped_at_buy_new():
    v = second_life_value(60.0, 0.9, [0.9] * 21, 10.0, W, 0.0, value_mult=100.0)
    assert v["capped"] and v["gross_energy_value_usd"] > v["buy_new_cap_usd"]
    cfg = load("economics.yaml")
    assert v["buy_new_cap_usd"] == pytest.approx(
        cfg["buy_new_benchmark"]["installed_system_usd_per_kwh"]["value"] * 60 * 0.9 * 10 / 15)


def test_shrinking_capacity_lowers_value():
    flat = second_life_value(60.0, 0.9, [0.9] * 21, 8.0, W, 0.0)["gross_energy_value_usd"]
    fading = second_life_value(60.0, 0.9, [0.9 - 0.03 * y for y in range(21)], 8.0, W, 0.0)
    assert fading["gross_energy_value_usd"] < flat


def test_value_is_not_lcos_times_years():
    v = second_life_value(60.0, 0.9, [0.9] * 21, 8.0, W, 0.0)
    assert v["net_usd"] != pytest.approx(v["lcos_usd_per_kwh"] * 8)


def test_sweep_is_labelled_illustrative_and_finds_flips():
    r = sweep(write=False)
    assert "ILLUSTRATIVE" in r["label"] and r["reference_battery"]["provenance"] == "synthetic"
    nmc = r["chemistries"]["NMC"]
    assert {g["decision"] for g in nmc["grid"]} == {"Second-Life", "Recycle"}


def test_clean_report_recommends_with_comparison(clean_bundle):
    r = assess(clean_bundle)
    assert r["economics"]["status"] == "ok"
    assert r["recommendation"]["option"] in ("Second-Life", "Recycle")
    assert "comparison_with_existing_rule" in r
    assert r["economics"]["placeholder_inputs"]
