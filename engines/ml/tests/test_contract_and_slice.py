from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest
from typer.testing import CliRunner

from revive_ml.cli import app
from revive_ml.contract import ContractError, Metadata, load_bundle, validate_telemetry, write_bundle
from revive_ml.convert import DEMO_SOURCE
from revive_ml.pipeline import INSUFFICIENT, assess
from revive_ml.provenance import untagged_numbers


def test_demo_conversion_mapping_is_explicit(demo_bundle):
    meta = demo_bundle.meta
    assert meta.chemistry == "NMC"  # the demo pack is NMC, not LFP
    assert (meta.series_cells, meta.parallel_cells) == (96, 40)
    assert meta.data_provenance == "synthetic"
    assert meta.current_sign_convention == "unknown"
    src = pd.read_csv(DEMO_SOURCE / "telemetry.csv")
    tel = demo_bundle.telemetry
    assert list(tel["current_a"]) == list(src["pack_current_A"])  # sign never flipped
    assert list(tel["voltage_v"]) == list(src["pack_voltage_V"])
    assert list(tel["temperature_c"]) == list(src["max_cell_temp_C"])
    assert len(meta.capacity_tests) == 5 and meta.capacity_tests[-1].measured_capacity_ah == 193.6


def test_missing_column_fails_loudly_with_hint():
    df = pd.read_csv(DEMO_SOURCE / "telemetry.csv")
    with pytest.raises(ContractError, match="pack_voltage_V' looks like 'voltage_v"):
        validate_telemetry(df)


def test_naive_timestamp_rejected(clean_bundle):
    df = clean_bundle.telemetry.copy()
    df["timestamp_utc"] = df["timestamp_utc"].dt.tz_localize(None)
    with pytest.raises(ContractError, match="timezone"):
        validate_telemetry(df)


def test_metadata_rejects_unknown_chemistry_and_bad_voltages(clean_bundle):
    d = clean_bundle.meta.model_dump()
    with pytest.raises(Exception, match="chemistry"):
        Metadata.model_validate({**d, "chemistry": "LCO"})
    with pytest.raises(Exception, match="min_voltage_v < nominal_voltage_v"):
        Metadata.model_validate({**d, "min_voltage_v": 400.0})
    with pytest.raises(Exception, match="extra"):
        Metadata.model_validate({**d, "pack_voltage_V": 1})


def test_asset_mismatch_rejected(clean_bundle):
    df = clean_bundle.telemetry.copy()
    df.loc[0, "asset_id"] = "OTHER"
    with pytest.raises(ContractError, match="OTHER"):
        validate_telemetry(df, clean_bundle.meta.asset_id)


def test_bundle_roundtrip_parquet_and_csv(clean_bundle, tmp_path: Path):
    for fmt in ("csv", "parquet"):
        p = write_bundle(tmp_path / fmt, clean_bundle.meta, clean_bundle.telemetry, fmt=fmt)
        b = load_bundle(p)
        assert len(b.telemetry) == len(clean_bundle.telemetry)
        assert b.telemetry["timestamp_utc"].iloc[1] - b.telemetry["timestamp_utc"].iloc[0] == pd.Timedelta(
            seconds=10)


def test_demo_report_makes_no_recommendation(demo_bundle):
    r = assess(demo_bundle)
    assert r["decision"] == INSUFFICIENT
    assert r["recommendation"] is None and r["economics"] is None
    assert untagged_numbers(r) == []


def test_clean_report_runs_every_stage_and_is_tagged(clean_bundle):
    r = assess(clean_bundle)
    assert r["data_quality"]["readiness"]["verdict"] == "READY_WITH_WARNINGS"
    assert r["gate"] is not None and r["state"] is not None
    assert untagged_numbers(r) == []
    json.dumps(r)  # serialisable


def test_cli_assess_and_contract_exit_code(tmp_path: Path):
    runner = CliRunner()
    bundle = tmp_path / "b"
    assert runner.invoke(app, ["convert-demo", "--out", str(bundle)]).exit_code == 0
    out = tmp_path / "r.json"
    res = runner.invoke(app, ["assess", str(bundle), "--out", str(out)])
    assert res.exit_code == 0, res.output
    assert json.loads(out.read_text())["decision"] == INSUFFICIENT
    res = runner.invoke(app, ["assess", str(DEMO_SOURCE)])
    assert res.exit_code == 2
