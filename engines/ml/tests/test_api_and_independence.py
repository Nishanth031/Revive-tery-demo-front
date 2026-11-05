from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd
from fastapi.testclient import TestClient

from revive_ml.api import app
from revive_ml.convert import DEMO_SOURCE
from revive_ml.pipeline import INSUFFICIENT

SRC = Path(__file__).resolve().parents[1] / "src"
FORBIDDEN = re.compile(r"^\s*(from|import)\s+(bms_engine|test_bench|esp32_sim|serial|paho|app)\b", re.M)


def test_no_forbidden_imports():
    for f in SRC.rglob("*.py"):
        assert not FORBIDDEN.search(f.read_text(encoding="utf-8")), f


def test_api_health_and_assess(demo_bundle):
    c = TestClient(app)
    assert c.get("/health").json()["status"] == "ok"
    tel = demo_bundle.telemetry.copy()
    tel["timestamp_utc"] = tel["timestamp_utc"].astype(str)
    body = {"metadata": json.loads(demo_bundle.meta.model_dump_json()),
            "telemetry": tel.to_dict("records")}
    r = c.post("/assess", json=body)
    assert r.status_code == 200, r.text
    assert r.json()["decision"] == INSUFFICIENT


def test_api_rejects_contract_violation(demo_bundle):
    raw = pd.read_csv(DEMO_SOURCE / "telemetry.csv")
    body = {"metadata": json.loads(demo_bundle.meta.model_dump_json()), "telemetry": raw.to_dict("records")}
    r = TestClient(app).post("/assess", json=body)
    assert r.status_code == 422 and "voltage_v" in r.text
