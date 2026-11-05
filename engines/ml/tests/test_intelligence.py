"""revive_ml.intelligence: column mapping, upload understanding, second-use advice (all additive)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from revive_ml.intelligence import (AdvisorInput, UploadError, advise, analyze_upload, assess_with_advice,
                                    map_columns, standardise)
from revive_ml.pipeline import assess
from revive_ml.synth import make_clean_bundle


def _messy(n=200) -> pd.DataFrame:
    rng = np.random.default_rng(0)
    return pd.DataFrame({
        "Cell Barcode": ["CELL-7"] * n, "Date Time": pd.date_range("2026-01-01", periods=n, freq="min").astype(str),
        "Test_Time(s)": np.arange(n) * 60.0, "Cycle No": np.repeat(np.arange(1, 5), n // 4),
        "Voltage (mV)": 3200 + rng.normal(0, 20, n), "Current(mA)": -rng.uniform(1000, 5000, n),
        "Temp [degF]": rng.uniform(70, 90, n), "Disch Cap (mAh)": np.linspace(50000, 49000, n),
        "SOC": np.linspace(1, 0.2, n), "Ambient Temp": 22.0, "Notes": ["ok"] * n, "Power kW": rng.normal(5, 1, n)})


# ----------------------------------------------------------------------------------------- mapper
def test_mapper_reads_messy_headers_and_converts_stated_units():
    r = map_columns(_messy(), "messy.csv")
    assert r.mapping == {"Cell Barcode": "battery_id", "Date Time": "timestamp_utc", "Test_Time(s)": "test_time_s",
                         "Cycle No": "cycle_index", "Voltage (mV)": "voltage_v", "Current(mA)": "current_a",
                         "Temp [degF]": "temperature_c", "Disch Cap (mAh)": "capacity_ah", "SOC": "soc_pct"}
    assert r.is_telemetry
    assert {u["column"] for u in r.unmapped} == {"Ambient Temp", "Notes", "Power kW"}
    std = standardise(_messy(), r, "messy.csv")
    assert 3.0 < std["voltage_v"].mean() < 3.4                          # mV -> V
    assert std["current_a"].max() < 0 and std["current_a"].min() > -6    # mA -> A, sign kept
    assert 20 < std["temperature_c"].mean() < 35                         # degF -> degC
    assert 40 < std["capacity_ah"].mean() < 55                           # mAh -> Ah
    assert 20 <= std["soc_pct"].min() <= 25 and std["soc_pct"].max() <= 100   # fraction -> %
    assert any("converted" in w for w in r.warnings)                    # every conversion is reported


def test_mapper_never_maps_by_values_alone_and_refuses_non_telemetry():
    df = pd.DataFrame({"colA": np.linspace(3.0, 4.2, 100), "colB": np.linspace(-5, 5, 100), "zzz": range(100)})
    r = map_columns(df, "anon.csv")
    assert r.matches == [] and not r.is_telemetry
    assert all(u["reason"] for u in r.unmapped)


def test_mapper_does_not_force_ambient_into_temperature():
    df = pd.DataFrame({"Voltage": np.linspace(3, 4, 50), "Ambient Temperature": 21.0})
    r = map_columns(df, "a.csv")
    assert r.mapping == {"Voltage": "voltage_v"}


# ----------------------------------------------------------------------------------------- upload understanding
def _csv(tmp_path, name, df):
    p = tmp_path / name
    df.to_csv(p, index=False)
    return p


def test_single_cell_upload_with_maker_name_is_fully_understood(tmp_path):
    df = _messy()
    df["Voltage (mV)"] = np.linspace(3300, 3100, len(df))
    a = analyze_upload([_csv(tmp_path, "BYD_blade_cell7.csv", df)])
    assert a.identity.brand == "BYD" and a.identity.chemistry == "LFP"
    b = a.batteries[0]
    assert b.spec.complete, b.spec.needs
    assert b.spec.chemistry.value == "LFP" and b.spec.series_cells.value == 1
    assert b.spec.rated_capacity_ah.basis == "inferred from data"


def test_a_voltage_window_is_a_hint_never_a_confirmation_of_chemistry(tmp_path):
    df = _messy()
    df["Voltage (mV)"] = np.linspace(3500, 3000, len(df))          # below 3.7 V: LFP-like, but also a partly discharged NMC
    s = analyze_upload([_csv(tmp_path, "cell_log.csv", df)]).batteries[0].spec
    assert "chemistry" in s.needs and s.chemistry.confident is False and "confirm" in s.chemistry.note
    df["Voltage (mV)"] = np.linspace(4150, 3000, len(df))          # reaches 4.15 V: not LFP, but NMC vs NCA is still open
    s = analyze_upload([_csv(tmp_path, "cell_log.csv", df)]).batteries[0].spec
    assert "chemistry" in s.needs and s.chemistry.value == "NMC" and s.chemistry.confident is False


def test_pack_voltage_does_not_reveal_series_count_so_it_is_asked_for(tmp_path):
    df = _messy()
    df["Voltage (mV)"] = np.linspace(350_000, 300_000, len(df))
    df["Disch Cap (mAh)"] = np.linspace(100_000, 98_000, len(df))
    a = analyze_upload([_csv(tmp_path, "pack.csv", df)], hints={"chemistry": "NMC"})
    assert a.batteries[0].spec.needs == ["series_cells"]
    a2 = analyze_upload([_csv(tmp_path, "pack.csv", df)], hints={"chemistry": "NMC", "series_cells": 96})
    assert a2.batteries[0].spec.complete and a2.batteries[0].spec.series_cells.basis == "user"


def test_ambiguous_maker_needs_a_chemistry_but_a_chemistry_name_settles_it(tmp_path):
    df = _messy()
    df["Voltage (mV)"] = np.linspace(350_000, 300_000, len(df))
    a = analyze_upload([_csv(tmp_path, "CATL_pack_2.csv", df)])
    assert a.identity.brand == "CATL" and a.identity.brand_ambiguous and a.identity.chemistry is None
    assert "chemistry" in a.batteries[0].spec.needs
    df2 = df.copy()
    df2["Cell Barcode"] = "CATL-LiFePO4-1"
    a2 = analyze_upload([_csv(tmp_path, "CATL_pack_2.csv", df2)])
    assert a2.identity.chemistry == "LFP" and "chemistry" not in a2.batteries[0].spec.needs


def test_metadata_table_in_the_upload_supplies_the_spec(tmp_path):
    meta = pd.DataFrame({"field": ["asset_id", "chemistry", "series_parallel_configuration", "nominal_capacity_Ah",
                                   "nominal_voltage_V", "manufacturer"],
                         "value": ["P1", "NMC (nickel manganese cobalt)", "96s40p", "200", "355.2", "LG Energy Solution"]})
    df = _messy()
    df["Voltage (mV)"] = np.linspace(380_000, 300_000, len(df))
    a = analyze_upload([_csv(tmp_path, "metadata.csv", meta), _csv(tmp_path, "telemetry.csv", df)])
    assert {t.source: t.role for t in a.tables} == {"metadata.csv": "metadata", "telemetry.csv": "telemetry"}
    s = a.batteries[0].spec
    assert s.complete and s.chemistry.value == "NMC" and s.series_cells.value == 96
    assert s.rated_capacity_ah.value == 200 and s.rated_capacity_ah.basis == "stated in upload"
    assert a.identity.brand == "LG Energy Solution"


def test_unreadable_or_non_telemetry_uploads_fail_clearly(tmp_path):
    p = tmp_path / "x.csv"
    p.write_text("a,b\n1,2\n3,4\n")
    with pytest.raises(UploadError):
        analyze_upload([p])
    with pytest.raises(UploadError):
        analyze_upload([])


# ----------------------------------------------------------------------------------------- advisor
def _opts(**nets):
    return {k: {"net_value": {"value": v}, "conservative_years": {"value": 6.0}} for k, v in nets.items()}


def test_lfp_favours_stationary_storage_over_vehicles():
    a = advise(AdvisorInput("LFP", soh_pct=88, gate="Pass", readiness="READY", decision="Second-Life: x"))
    assert a["status"] == "ranked"
    order = [s["application"] for s in a["suggestions"]]
    assert order[0] in ("residential_storage", "commercial_peak_shaving") and order[-1] == "low_speed_ev"


def test_nmc_ranks_the_vehicle_application_higher_than_lfp_does():
    nmc = {s["application"]: s["rank"] for s in advise(AdvisorInput("NMC", soh_pct=88, gate="Pass"))["suggestions"]}
    lfp = {s["application"]: s["rank"] for s in advise(AdvisorInput("LFP", soh_pct=88, gate="Pass"))["suggestions"]}
    assert nmc["low_speed_ev"] < lfp["low_speed_ev"]


def test_health_excludes_applications_the_battery_cannot_serve():
    a = advise(AdvisorInput("LFP", soh_pct=62, gate="Pass"))
    assert {e["application"] for e in a["excluded"]} >= {"commercial_peak_shaving", "low_speed_ev"}
    assert "commercial_peak_shaving" not in {s["application"] for s in a["suggestions"]}


def test_safety_verdicts_are_never_overruled():
    assert advise(AdvisorInput("LFP", soh_pct=95, gate="Reject"))["suggestions"] == []
    assert advise(AdvisorInput("NMC", soh_pct=95, decision="Recycle"))["status"] == "none"
    q = advise(AdvisorInput("LFP", soh_pct=85, gate="Quarantine", decision="Inspection required"))
    assert q["status"] == "provisional" and all(s["tier"] == "provisional" for s in q["suggestions"])
    n = advise(AdvisorInput("LFP", soh_pct=85, readiness="NOT_READY", decision="Insufficient or untrustworthy data"))
    assert n["status"] == "provisional" and "quality" in " ".join(n["notes"])
    assert advise(AdvisorInput("", soh_pct=90))["status"] == "none"          # unknown chemistry: no guess


def test_failed_data_says_fix_the_data_not_that_health_is_too_low():
    a = advise(AdvisorInput("LFP", soh_pct=None, readiness="NOT_READY", decision="Insufficient or untrustworthy data"))
    assert a["status"] == "none" and a["next_step"] == "fix_data" and "data" in a["headline"]


def test_engine_economics_move_the_ranking():
    r = advise(AdvisorInput("LFP", soh_pct=90, gate="Pass", economics_options=_opts(
        residential_storage=100, commercial_peak_shaving=5000, telecom_backup=100, low_speed_ev=100)))
    assert r["suggestions"][0]["application"] == "commercial_peak_shaving"
    assert r["suggestions"][0]["components"]["economics"] == 1.0


def test_assess_with_advice_leaves_the_engine_report_unchanged():
    b = make_clean_bundle(seed=0)
    plain = assess(b)
    out = assess_with_advice(b)
    advice = out.pop("advice")
    for k in ("decision", "gate", "state", "economics", "recommendation", "rationale"):
        assert out[k] == plain[k]
    assert advice["status"] == "ranked" and advice["battery"]["chemistry"] == plain["chemistry"]
    assert advice["suggestions"][0]["application"] in plain["economics"]["second_life_options"]
