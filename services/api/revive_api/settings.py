"""Backend settings: paths and limits. Everything runs locally; nothing here is exposed to a network.

Importing this module points the BMS engine at the configured database, so every part of the
backend (runs, batteries, uploads, assessments) reads and writes the same DuckDB file.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Platform root: REVIVE_PLATFORM_ROOT, else three folders up (services/api/revive_api -> platform).
APP_ROOT = Path(os.environ.get("REVIVE_PLATFORM_ROOT") or Path(__file__).resolve().parents[3])
ENGINE_DIRS = [APP_ROOT / "engines" / name for name in ("bms", "lite", "database")]  # flat-import engines

# REVIVE_DB lets tests and demos use a copy without touching the project database.
DB_PATH = Path(os.environ.get("REVIVE_DB") or APP_ROOT / "data" / "db" / "revive_tery.duckdb")

MAX_UPLOAD_BYTES = 200 * 1024 * 1024
ALLOWED_UPLOAD_SUFFIXES = {".csv", ".xlsx", ".xls", ".zip"}
TELEMETRY_PREVIEW_ROWS = 5000
STALE_READING_S = 3.0   # the firmware sends a reading every second (same limit as the Dash app)

# Local front ends allowed to call the API from a browser (Vite dev server and a local build).
CORS_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:4173", "http://127.0.0.1:4173"]

for _engine_dir in reversed(ENGINE_DIRS):
    if str(_engine_dir) not in sys.path:
        sys.path.insert(0, str(_engine_dir))

import bms_engine  # noqa: E402  (needs engines/bms on the path)

bms_engine.DB_PATH = DB_PATH
