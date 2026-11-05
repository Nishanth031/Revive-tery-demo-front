# REVIVE-TERY platform tasks. Install `just` once:  pip install rust-just   (then run: just <task>)
# Use your own interpreter by setting REVIVE_PY (e.g. the venv python); default is `python` on PATH.

set windows-shell := ["powershell.exe", "-NoLogo", "-NoProfile", "-Command"]
set dotenv-load := false

py  := env_var_or_default("REVIVE_PY", "python")
sep := if os_family() == "windows" { ";" } else { ":" }
# Circuit Studio and the API import these folders as flat top-level modules (bms_engine, ml_engine_bridge, ...)
root := justfile_directory()
export PYTHONPATH := root + "/engines/bms" + sep + root + "/engines/lite" + sep + root + "/engines/database"
export REVIVE_PLATFORM_ROOT := root
export PYTHONIOENCODING := "utf-8"

default:
    @just --list

# ---- migration and guard rails -------------------------------------------------
migrate-dry:
    {{py}} scripts/migrate_from_legacy.py

migrate:
    {{py}} scripts/migrate_from_legacy.py --apply

check:
    {{py}} scripts/check_contracts.py
    {{py}} engines/firmware/tools/check_monitor_only.py
    {{py}} scripts/check_circuit.py

# firmware: compile both range profiles (arduino-cli); copy the sketch + regenerate circuit.json; Wokwi lint/run if available
fw-build:
    {{py}} scripts/fw_build.py

wokwi-sync:
    {{py}} scripts/wokwi_sync.py

wokwi-check:
    {{py}} scripts/wokwi_check.py

test-bms:
    {{py}} -m pytest engines/bms/test_firmware_lines.py -q

# What do I re-run after my edits?  just impact   |   just impact engines/ml/src/revive_ml/gate/ood.py
impact *files:
    {{py}} scripts/impact.py {{files}}

# ---- tests ---------------------------------------------------------------------
test-ml:
    cd engines/ml; {{py}} -m pytest

test-api:
    {{py}} -m pytest services/api/tests -q

test-web:
    cd apps/web-studio; npm test

test-relife:
    cd apps/relife-studio; {{py}} -m unittest discover -s tests

test-db:
    {{py}} -m pytest engines/database/test_fleet.py -q

test-all: check test-ml test-db test-bms test-api test-web test-relife

# ---- run -----------------------------------------------------------------------
# user's 60-pack fleet + platform packs + test cases, dense SYNTHETIC telemetry, views, runtime tables
db:
    {{py}} engines/database/import_fleet.py

# assess every pack with the engine (writes fleet_reports)
fleet:
    {{py}} engines/database/fleet_reports.py --source dense

# rebuild the DB, assess the fleet and refresh the web app's copy (DuckDB-WASM file, CSVs, db_meta, history)
web-db:
    {{py}} engines/database/refresh_web_copy.py

studio:
    {{py}} apps/circuit-studio/app.py

api:
    cd services/api; {{py}} -m uvicorn revive_api.main:app --host 127.0.0.1 --port 8000

web:
    cd apps/web-studio; {{py}} -m http.server 8080

relife:
    cd apps/relife-studio; {{py}} main.py

# copy the decision map into the web app (the one hand-copied file under apps/web-studio/data)
sync-config:
    {{py}} -c "import shutil; shutil.copy2('config/decision_map.json', 'apps/web-studio/data/decision_map.json')"

# ---- regenerate the browser engines after a Python engine changed -------------------
web-regen:
    cd apps/web-studio; {{py}} tools/export_assets.py; {{py}} tools/make_golden.py; node tools/make_bundles.mjs; node tools/make_fleet_reports.mjs; npm test
