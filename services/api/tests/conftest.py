"""Tests run against a scratch COPY of the project database: set REVIVE_DB before the API is imported."""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import pytest

APP_ROOT = Path(__file__).resolve().parents[3]  # platform root (services/api/tests -> platform)
SAMPLES = APP_ROOT / "engines" / "database" / "ml_samples"
ML_EXAMPLES = APP_ROOT / "engines" / "ml" / "examples"

_scratch = Path(tempfile.mkdtemp(prefix="revive_api_tests_"))
shutil.copy2(APP_ROOT / "data" / "db" / "revive_tery.duckdb", _scratch / "test.duckdb")
os.environ["REVIVE_DB"] = str(_scratch / "test.duckdb")


@pytest.fixture(scope="session")
def client():
    from fastapi.testclient import TestClient

    from revive_api.main import app

    with TestClient(app) as c:        # runs the lifespan: creates ml_* and assessments tables
        yield c
    shutil.rmtree(_scratch, ignore_errors=True)


@pytest.fixture(scope="session")
def samples() -> Path:
    return SAMPLES


@pytest.fixture(scope="session")
def ml_examples() -> Path:
    return ML_EXAMPLES
