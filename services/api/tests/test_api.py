from __future__ import annotations

import io
import time
import zipfile

import numpy as np
import pandas as pd
import pytest

SPEC_PACK = {"chemistry": "LFP", "series_cells": 16, "rated_capacity_ah": 100}


def _upload(client, paths, provenance="synthetic"):
    files = [("files", (p.name, p.read_bytes())) for p in paths]
    return client.post("/api/uploads", files=files, data={"data_provenance": provenance})


def _wait_not_running(client, seconds=15):
    end = time.time() + seconds
    while time.time() < end:
        cur = client.get("/api/runs/current").json()
        if not cur["running"]:
            return cur
        time.sleep(0.1)
    raise AssertionError("run did not finish in time")


# ------------------------------------------------------------------ system and batteries
def test_health_and_tables(client):
    h = client.get("/api/health").json()
    assert h["status"] == "ok" and h["database"]["available"] is True
    assert {"ml_telemetry", "ml_ingest_log", "assessments", "telemetry", "test_run_log"} <= set(h["database"]["tables"])


def test_demo_battery_listing_and_detail(client):
    items = client.get("/api/batteries").json()
    demo = next(b for b in items if b["id"] == "DEMO-EV-PACK-001")
    assert demo["kind"] == "database" and demo["data_provenance"] == "synthetic" and demo["rated_capacity_ah"] == 200
    d = client.get("/api/batteries/DEMO-EV-PACK-001").json()
    assert len(d["health_history"]) == 5 and len(d["telemetry"]) == 12 and len(d["modules"]) == 4
    assert d["telemetry"][0]["timestamp_utc"].startswith("2026-10-20T08:00:00")
    assert client.get("/api/batteries/NOPE").status_code == 404


# ------------------------------------------------------------------ runs
def test_virtual_replay_run_and_conflict(client):
    r = client.post("/api/runs", json={"source": "virtual", "battery_id": "DEMO-EV-PACK-001", "delay_s": 0.2})
    assert r.status_code == 201 and r.json()["running"] is True
    assert client.post("/api/runs", json={"source": "virtual", "delay_s": 0.2}).status_code == 409
    done = _wait_not_running(client)
    assert done["status"] == "finished" and len(done["readings"]) == 12
    assert done["decision"]["use_case"] and "rows" not in done["log_note"] or "logged" in done["log_note"]
    first = done["readings"][0]
    assert {"voltage_v", "current_a", "soc_pct", "soh_live_pct"} <= set(first)


def test_stream_cursor_returns_only_new_readings(client):
    from revive_api.services import runs

    full = runs.snapshot_json(tail=600)
    assert len(full["readings"]) == 12
    ts = full["readings"][5]["timestamp"]
    newer = runs.snapshot_json(since_ts=ts)
    assert [x["timestamp"] for x in newer["readings"]] == [x["timestamp"] for x in full["readings"][6:]]


def test_simulated_run_fault_injection_and_stop(client):
    faults = {f["id"] for f in client.get("/api/faults").json()}
    assert "none" in faults and len(faults) >= 5
    r = client.post("/api/runs", json={"source": "simulated", "simulation": {"speed": 600, "load_current_a": 2.0}})
    assert r.status_code == 201 and r.json()["simulated"] is True and r.json()["mode"] == "simulated"
    assert client.post("/api/runs/fault", json={"fault": "not-a-fault"}).status_code == 422
    fault = next(f for f in faults if f != "none")
    assert client.post("/api/runs/fault", json={"fault": fault}).status_code == 200
    client.post("/api/runs/stop")
    done = _wait_not_running(client)
    assert done["status"] in ("stopped", "finished", "error") and done["simulated"] is True


def test_run_validation(client):
    assert client.post("/api/runs", json={"source": "simulated", "simulation": {"speed": 99999}}).status_code == 422
    assert client.post("/api/runs", json={"source": "simulated", "simulation": {"load_current_a": 9}}).status_code == 422
    assert client.post("/api/runs", json={"source": "hardware"}).status_code == 422
    assert client.post("/api/runs/fault", json={"fault": "none"}).status_code == 409   # nothing running
    assert isinstance(client.get("/api/ports").json(), list)


# ------------------------------------------------------------------ uploads
def test_upload_maps_columns_and_rejects_bad_types(client, samples):
    r = _upload(client, [samples / "1_healthy_pack.csv", samples / "2_worn_pack.csv",
                         samples / "3_overdischarged_pack.csv", samples / "4_no_capacity_in_zip.zip",
                         samples / "5_end_of_life_pack.csv"])
    assert r.status_code == 201, r.text
    body = r.json()
    assert set(body["battery_ids"]) >= {"PACK-HEALTHY", "PACK-WORN", "PACK-OVERDISCHARGED", "PACK-NOCAP",
                                        "PACK-END-OF-LIFE"}
    m = body["column_mappings"]["1_healthy_pack.csv"]
    assert m["mapped"]["Voltage (V)"] == "voltage_v" and m["unmapped"] == []
    ids = {b["id"]: b for b in client.get("/api/batteries").json()}
    assert ids["PACK-HEALTHY"]["kind"] == "uploaded" and ids["PACK-HEALTHY"]["data_provenance"] == "synthetic"
    d = client.get("/api/batteries/PACK-HEALTHY").json()
    assert len(d["capacity_per_cycle"]) == 120
    bad = client.post("/api/uploads", files=[("files", ("notes.txt", b"hello"))], data={"data_provenance": "synthetic"})
    assert bad.status_code == 422 and bad.json()["code"] == "ingestion_failed"
    assert client.post("/api/uploads", files=[("files", ("a.csv", b"x"))],
                       data={"data_provenance": "real"}).status_code == 422
    assert len(client.get("/api/uploads").json()) >= 5


# ------------------------------------------------------------------ assessments
def test_demo_pack_with_dense_telemetry_reaches_a_decision(client):
    """The default for database packs is the densified SYNTHETIC series, which the engine can assess."""
    r = client.post("/api/assessments", json={"battery_id": "DEMO-EV-PACK-001"})
    assert r.status_code == 201, r.text
    s = r.json()["summary"]
    assert s["readiness"] != "NOT_READY" and s["decision"] != "Insufficient or untrustworthy data"
    assert r.json()["report"]["data_provenance"] == "synthetic"


def test_demo_pack_is_refused_by_data_quality_and_persisted(client):
    # the pack's own 12 original rows are inconsistent with its capacity tests: the engine refuses them
    r = client.post("/api/assessments", json={"battery_id": "DEMO-EV-PACK-001", "telemetry_source": "original"})
    assert r.status_code == 201, r.text
    a = r.json()
    s = a["summary"]
    assert a["engine"] == "full" and s["decision"] == "Insufficient or untrustworthy data"
    assert s["readiness"] == "NOT_READY" and s["gate"] is None
    failed = {c["id"] for c in s["failed_checks"]}
    assert {"charge_balance", "regen_sign", "estimate_disagreement"} <= failed
    assert {c["id"] for c in s["inconclusive_checks"]} == {"resistance"}
    assert s["legacy_rule"] == "Second-Life: stationary storage"     # the old rule would have approved it
    assert s["capacity_test_soh_pct"] == 96.8 and s["soh_pct"] is None
    assert a["report"]["recommendation"] is None
    again = client.get(f"/api/assessments/{a['id']}").json()
    assert again["summary"]["decision"] == s["decision"] and again["report"]["asset_id"] == "DEMO-EV-PACK-001"
    listed = client.get("/api/assessments", params={"battery_id": "DEMO-EV-PACK-001"}).json()
    assert any(x["id"] == a["id"] for x in listed)


def test_upload_without_timestamps_falls_back_to_lite_with_reason(client):
    r = client.post("/api/assessments", json={"battery_id": "PACK-HEALTHY", "spec": SPEC_PACK})
    assert r.status_code == 201, r.text
    s = r.json()["summary"]
    assert s["engine"] == "lite" and s["decision"].startswith("Second-Life Reuse")
    assert any("Full ML engine skipped" in w and "timestamp" in w for w in s["warnings"])
    assert 90 < s["soh_pct"] < 97 and s["gate"] == "Pass"
    worn = client.post("/api/assessments", json={"battery_id": "PACK-WORN", "spec": SPEC_PACK}).json()["summary"]
    assert worn["decision"].startswith("Repurpose")
    over = client.post("/api/assessments", json={"battery_id": "PACK-OVERDISCHARGED", "spec": SPEC_PACK}).json()["summary"]
    assert over["gate"] == "Reject" and over["decision"] == "Recycle"
    nocap = client.post("/api/assessments", json={"battery_id": "PACK-NOCAP", "spec": SPEC_PACK}).json()["summary"]
    assert nocap["decision"] == "Insufficient data"


def test_forcing_full_engine_on_incomplete_upload_is_refused(client):
    r = client.post("/api/assessments", json={"battery_id": "PACK-HEALTHY", "engine": "full", "spec": SPEC_PACK})
    assert r.status_code == 422 and r.json()["code"] == "cannot_assess" and "timestamp" in r.json()["detail"]
    assert client.post("/api/assessments", json={"battery_id": "NOPE"}).status_code == 404
    assert client.get("/api/assessments/does-not-exist").status_code == 404


def test_timestamped_upload_reaches_the_full_engine(client):
    from revive_ml.synth import make_clean_bundle

    b = make_clean_bundle(seed=0)
    df = b.telemetry.copy()
    df["asset_id"] = "UPLOAD-TIMED"
    df["cycle_index"] = np.arange(len(df)) // 200 + 1
    df["capacity_ah"] = 92.0 * (1 - 0.0005 * df["cycle_index"])
    csv = df[["asset_id", "timestamp_utc", "cycle_index", "voltage_v", "current_a", "temperature_c",
              "capacity_ah", "soc_pct"]].to_csv(index=False).encode()
    up = client.post("/api/uploads", files=[("files", ("timed.csv", csv))], data={"data_provenance": "synthetic"})
    assert up.status_code == 201, up.text
    r = client.post("/api/assessments", json={"battery_id": "UPLOAD-TIMED",
                                              "spec": {"chemistry": "LFP", "series_cells": 96, "rated_capacity_ah": 100}})
    assert r.status_code == 201, r.text
    a = r.json()
    assert a["engine"] == "full" and a["summary"]["readiness"] in ("READY", "READY_WITH_WARNINGS", "NOT_READY")
    assert a["report"]["asset_id"] == "UPLOAD-TIMED" and a["report"]["data_provenance"] == "synthetic"


def test_contract_bundle_zip_runs_the_full_engine(client, ml_examples):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name in ("metadata.json", "telemetry.csv"):
            z.write(ml_examples / "clean_synthetic_bundle" / name, name)
    r = client.post("/api/assessments/bundle", files={"bundle": ("clean.zip", buf.getvalue())})
    assert r.status_code == 201, r.text
    a = r.json()
    assert a["engine"] == "full" and a["battery_id"] == "SYNTH-CLEAN-001"
    assert a["summary"]["readiness"] == "READY_WITH_WARNINGS" and a["summary"]["gate"] == "Pass"
    assert a["summary"]["decision"].startswith("Second-Life")
    assert a["report"]["projections"] and a["report"]["economics"]["placeholder_inputs"]
    bad = client.post("/api/assessments/bundle", files={"bundle": ("x.zip", b"not a zip")})
    assert bad.status_code == 422 and bad.json()["code"] == "cannot_assess"


def test_project_database_was_not_touched_by_tests(client):
    from revive_api import settings

    assert "revive_api_tests_" in str(settings.DB_PATH)
