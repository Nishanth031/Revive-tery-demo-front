"""/api/intelligence: the ML reads messy uploads, stores them, assesses and advises a second use."""
from __future__ import annotations

import numpy as np
import pandas as pd


def _messy_pack_csv(battery_id: str) -> bytes:
    """A timestamped LFP pack log with vendor-style headers and mV / mA / mAh units (same data as the clean bundle)."""
    from revive_ml.synth import make_clean_bundle

    df = make_clean_bundle(seed=0).telemetry.copy()
    cycle = np.arange(len(df)) // 200 + 1
    out = pd.DataFrame({
        "Pack Serial": battery_id, "Logged At": df["timestamp_utc"].astype(str), "Cycle No": cycle,
        "Pack Voltage (mV)": df["voltage_v"] * 1000, "Current (mA)": df["current_a"] * 1000,
        "Temp [degC]": df["temperature_c"], "Capacity (mAh)": 92_000.0,       # flat: a log of a few days says nothing about fade, so none is invented
        "SOC (%)": df["soc_pct"], "Ambient Temp": 22.0, "Notes": "bench log"})
    return out.to_csv(index=False).encode()


def test_map_is_a_dry_run_that_stores_nothing(client):
    before = len(client.get("/api/uploads").json())
    r = client.post("/api/intelligence/map", files=[("files", ("BYD_pack_log.csv", _messy_pack_csv("MAP-ONLY")))],
                    data={"series_cells": "96"})
    assert r.status_code == 200, r.text
    a = r.json()["analysis"]
    mapped = {m["column"]: m["field"] for m in a["tables"][0]["mapping"]["mapped"]}
    assert mapped["Pack Voltage (mV)"] == "voltage_v" and mapped["Current (mA)"] == "current_a"
    assert mapped["Capacity (mAh)"] == "capacity_ah" and mapped["Pack Serial"] == "battery_id"
    assert a["identity"]["brand"] == "BYD" and a["identity"]["chemistry"] == "LFP"
    assert r.json()["stored"] is None and len(client.get("/api/uploads").json()) == before
    assert "MAP-ONLY" not in [b["id"] for b in client.get("/api/batteries").json()]


def test_analyze_maps_stores_assesses_and_advises(client):
    r = client.post("/api/intelligence/analyze", files=[("files", ("BYD_pack_log.csv", _messy_pack_csv("ML-LFP-1")))],
                    data={"data_provenance": "synthetic", "series_cells": "96", "rated_capacity_ah": "100"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["stored"]["rows_inserted"] > 0 and "ML-LFP-1" in body["stored"]["battery_ids"]
    res = body["results"][0]
    assert res["status"] == "assessed" and res["engine"] == "full"
    advice = res["advice"]
    assert advice["battery"]["chemistry"] == "LFP" and advice["battery"]["brand"]["name"] == "BYD"
    assert advice["status"] in ("ranked", "provisional") and advice["suggestions"]
    assert advice["suggestions"][0]["application"] in ("residential_storage", "commercial_peak_shaving", "telecom_backup")
    # the data really landed converted to engine units, and the identity and advice were saved
    tel = client.get("/api/batteries/ML-LFP-1").json()
    assert 2.5 < tel["telemetry"][0]["voltage_v"] * 1 / 96 < 4.3, "mV was converted to V"
    assert any(b["id"] == "ML-LFP-1" for b in client.get("/api/batteries").json())
    assert client.get("/api/intelligence/suggestions", params={"battery_id": "ML-LFP-1"}).json()
    assert client.get(f"/api/assessments/{res['id']}").json()["report"].get("advice") is None   # report is untouched


def test_analyze_asks_instead_of_guessing_what_it_cannot_know(client):
    csv = _messy_pack_csv("ML-NEEDS-1")                     # a pack: series count and chemistry are not in the file
    r = client.post("/api/intelligence/analyze", files=[("files", ("pack_log.csv", csv))],
                    data={"data_provenance": "synthetic"})
    assert r.status_code == 201, r.text
    res = r.json()["results"][0]
    assert res["status"] == "needs_input" and set(res["needs"]) >= {"series_cells", "chemistry"}
    assert r.json()["stored"]["rows_inserted"] > 0          # the data is kept, the assessment waits
    again = client.post("/api/intelligence/advise", json={"battery_id": "ML-NEEDS-1"})
    assert again.status_code == 422 and again.json()["code"] == "needs_input"
    done = client.post("/api/intelligence/advise", json={
        "battery_id": "ML-NEEDS-1", "spec": {"chemistry": "LFP", "series_cells": 96, "rated_capacity_ah": 100}})
    assert done.status_code == 201, done.text
    assert done.json()["engine"] == "full" and done.json()["advice"]["suggestions"]


def test_advise_a_database_pack_uses_its_own_chemistry(client):
    lfp = client.post("/api/intelligence/advise", json={"battery_id": "DEMO-LFP-PACK-004"})
    assert lfp.status_code == 201, lfp.text
    a = lfp.json()["advice"]
    assert a["battery"]["chemistry"] == "LFP" and a["status"] in ("ranked", "provisional") and a["suggestions"]
    nmc = client.post("/api/intelligence/advise", json={"battery_id": "DEMO-EV-PACK-002"}).json()["advice"]
    assert nmc["battery"]["chemistry"] == "NMC" and nmc["suggestions"]
    rank = lambda adv: {s["application"]: s["rank"] for s in adv["suggestions"]}      # noqa: E731
    assert rank(nmc)["low_speed_ev"] < rank(a)["low_speed_ev"]                      # the vehicle fit differs by chemistry
    # a pack the engine's safety gate rejects (recorded resistance ratio above 2x) gets no second-use suggestion
    recycle = client.post("/api/intelligence/advise", json={"battery_id": "DEMO-LFP-PACK-005"}).json()
    assert recycle["advice"]["status"] == "none" and recycle["advice"]["next_step"] == "recycle"
    assert client.post("/api/intelligence/advise", json={"battery_id": "NOPE"}).status_code == 404


def test_unreadable_upload_and_bad_hints_are_422(client):
    junk = client.post("/api/intelligence/map", files=[("files", ("x.csv", b"a,b\n1,2\n3,4\n"))])
    assert junk.status_code == 422 and junk.json()["code"] == "unreadable_upload"
    bad = client.post("/api/intelligence/map", files=[("files", ("x.csv", b"a\n1"))], data={"chemistry": "LEAD"})
    assert bad.status_code == 422


def test_profiles_catalog_is_labelled_assumed(client):
    p = client.get("/api/intelligence/profiles").json()
    assert set(p["chemistries"]) == {"LFP", "NMC", "NCA"} and p["provenance"] == "assumed"
    assert any(b["name"] == "BYD" and b["chemistry"] == "LFP" and not b["ambiguous"] for b in p["brands"])
    assert any(b["name"] == "CATL" and b["ambiguous"] for b in p["brands"])
