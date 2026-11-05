"""/api/fleet and friends on the scratch copy of the fleet database (60+ packs)."""
from __future__ import annotations


def test_fleet_lists_60_plus_with_paging_filters_and_sort(client):
    r = client.get("/api/fleet", params={"limit": 10})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] >= 60 and len(body["packs"]) == 10
    page2 = client.get("/api/fleet", params={"limit": 10, "offset": 10}).json()["packs"]
    assert {p["asset_id"] for p in page2}.isdisjoint({p["asset_id"] for p in body["packs"]})
    rep = client.get("/api/fleet", params={"disposition": "REPURPOSE", "limit": 500}).json()
    assert rep["total"] > 0 and all(p["disposition"] == "REPURPOSE" for p in rep["packs"])
    lfp = client.get("/api/fleet", params={"chemistry": "LFP", "limit": 500}).json()["packs"]
    assert lfp and all(p["chemistry"] == "LFP" for p in lfp)
    flaws = client.get("/api/fleet", params={"source": "test", "limit": 500}).json()["packs"]
    assert len(flaws) == 6 and all(p["test_case"] for p in flaws)
    q = client.get("/api/fleet", params={"q": "flaw-03"}).json()["packs"]
    assert [p["asset_id"] for p in q] == ["DEMO-FLAW-03"]
    nv = [p["net_value"] for p in client.get("/api/fleet", params={"sort": "net_value", "desc": True, "limit": 5}).json()["packs"]]
    assert nv == sorted(nv, reverse=True)


def test_fleet_summary_adds_up(client):
    s = client.get("/api/fleet/summary").json()
    assert sum(s["by_disposition"].values()) == s["n"] >= 60
    f = s["funnel"]
    assert f["total"] >= f["data_quality_ready"] >= f["gate_pass"] >= f["state_ok"]
    assert f["second_life_chosen"] == s["by_disposition"]["REUSE"] + s["by_disposition"]["REPURPOSE"]


def test_battery_detail_history_and_passport(client):
    aid = client.get("/api/fleet", params={"disposition": "REPURPOSE", "limit": 1}).json()["packs"][0]["asset_id"]
    b = client.get(f"/api/battery/{aid}").json()
    assert b["report"]["decision"].startswith("Second-Life") and b["insight"]["confidence"]["label"] == "heuristic"
    h = client.get(f"/api/battery/{aid}/history").json()
    assert len(h) >= 3 and {"assessment_date", "soh_pct", "resistance_mohm"} <= set(h[0])
    pp = client.get(f"/api/battery/{aid}/passport").json()
    assert pp["note"] == "informational, not a regulatory document" and len(pp["input_telemetry_sha256"]) == 64
    assert client.get("/api/battery/NOPE").status_code == 404


def test_whatif_flips_with_the_tariff_and_plan_respects_limits(client):
    p = client.get("/api/fleet", params={"disposition": "REPURPOSE", "limit": 1}).json()["packs"][0]
    be = p["insight"]["robustness"]["break_even_tariff"]
    lo = client.post("/api/whatif", json={"asset_id": p["asset_id"], "overrides": {"tariff": be - 0.01}}).json()
    hi = client.post("/api/whatif", json={"asset_id": p["asset_id"], "overrides": {"tariff": be + 0.01}}).json()
    assert lo["decision"].split(":")[0] != hi["decision"].split(":")[0]
    assert client.post("/api/whatif", json={"asset_id": p["asset_id"], "region": "atlantis"}).status_code == 422
    plan = client.post("/api/fleet/plan", json={"limits": {"residential_storage": {"packs": 3}, "telecom_backup": {"packs": 1}}}).json()
    assert plan["by_application"]["residential_storage"]["packs"] <= 3 and plan["by_application"]["telecom_backup"]["packs"] <= 1


def test_meta_and_history(client):
    m = client.get("/api/meta").json()
    assert m["n_assets"] >= 60 and m["table_counts"]["telemetry_dense"] >= 60_000 and m["engine_version"]
    assert isinstance(client.get("/api/history/assessments").json(), list)
    assert isinstance(client.get("/api/history/suggestions").json(), list)
    assert isinstance(client.get("/api/history/runs").json(), list)


def test_refresh_rewrites_fleet_reports_in_one_writer(client):
    r = client.post("/api/fleet/refresh")
    assert r.status_code == 201, r.text
    assert r.json()["refreshed"] >= 60 and r.json()["errors"] == 0
    assert client.get("/api/fleet/summary").json()["n"] == r.json()["refreshed"]
