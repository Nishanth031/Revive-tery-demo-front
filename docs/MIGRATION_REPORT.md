# Migration report

Date: 2026-11-05. Python 3.13.14, Node 24.22.1, git 2.56.0 (Windows, PowerShell).
The five legacy folders were only read; nothing in them was changed.

## 1. What was copied

`python scripts/migrate_from_legacy.py --apply`: **45 entries, 262 files, 37.1 MB**. The dry run showed 0 MISSING sources, so `migration_manifest.json` did not need changes. `check_contracts.py` afterwards: `0 error(s), 0 warning(s)`.
Summary: ML engine to `engines/ml`, API to `services/api`, BMS/lite/database code to `engines/{bms,lite,database}`, Dash app to `apps/circuit-studio`, ReLife to `apps/relife-studio`, web app to `apps/web-studio`, DuckDB to `data/db/revive_tery.duckdb`, legacy docs to `docs/legacy/`.

## 2. Environments

- `~/venvs/revive-platform` (py 3.13): `engines/ml[dev,api]`, API and Circuit Studio requirements, `rust-just`. All installed from wheels (`--only-binary=:all:`), no failures.
- `~/venvs/revive-relife` (py 3.13): ReLife requirements. Installed OK.
- `apps/web-studio`: `npm install` OK.
- `revive_ml.paths.CONFIG_DIR.exists()`: `True` (paths.py not edited).

## 3. Path edits (file: change)

| File | Change |
|---|---|
| `services/api/revive_api/settings.py` | `APP_ROOT` = `REVIVE_PLATFORM_ROOT` or `parents[3]`. `SRC_DIR` replaced by `engines/{bms,lite,database}` on `sys.path`. Default DB is `data/db/revive_tery.duckdb` (`REVIVE_DB` still wins). |
| `services/api/tests/conftest.py` | Root `parents[3]`. Samples come from `engines/database/ml_samples`, ML examples from `engines/ml/examples`, and the scratch DB is copied from `data/db/`. |
| `engines/bms/bms_engine.py` | `PROJECT_ROOT` = `parents[2]`; `DB_PATH` = `REVIVE_DB` or `data/db/...` (+ `import os`) |
| `engines/database/build_relational_db.py` | `PROJECT_ROOT` = `parents[2]`; `CSV_DIR` = `engines/database/csv_bundle`; `DB_PATH` = `REVIVE_DB` or `data/db/...` (+ `import os`) |
| `engines/database/make_ml_samples.py` | output is `engines/database/ml_samples` |
| `engines/lite/ml_analyzer_suggester.py` | `DEFAULT_DB_PATH` = `REVIVE_DB` or platform `data/db/...`; it was cwd-relative before (+ `import os`) |
| `apps/circuit-studio/backend_connector.py` | `DB_PATH` = `REVIVE_DB` or platform `data/db/...` (+ `import os`) |
| `apps/circuit-studio/ml_panel.py` | `DB_PATH` = `REVIVE_ML_DB`, then `REVIVE_DB`, then platform `data/db/...` |
| `apps/relife-studio/database.py` | added the candidate `<root>/data/db/revive_tery.duckdb` in `discover_database` |
| `apps/web-studio/tools/export_assets.py` | `ROOT` = platform root. `ML` = `engines/ml`, `RELIFE` = `apps/relife-studio`. CSV bundle, samples, firmware and `app.py` read from their platform paths. |
| `apps/web-studio/tools/make_golden.py` | `ROOT` = platform root. `ML` = `engines/ml`, `RELIFE` = `apps/relife-studio`. `sys.path` has `engines/ml/src`, `engines/bms` and `engines/lite`. |
| `apps/web-studio/tools/make_bundles.mjs` | no change needed (no legacy paths; it reads `tests/golden/` only) |

Checks: `just db` built `data/db/revive_tery.duckdb`. `just api` then `GET /api/health` returned `{"status":"ok", ... "database": {"available": true}}`.

## 4. Test suites

| Suite | Command | Result |
|---|---|---|
| Contracts | `just check` | 0 errors, 0 warnings |
| ML | `just test-ml` | **89 passed**, 0 failed (2 deprecation warnings) |
| DB build | `just db` | OK |
| API | `just test-api` | **13 passed** (18 after the disposition tests were added) |
| ReLife | `just test-relife` (relife venv) | **39 tests OK** |
| Web parity | `just test-web` | **41 passed**, 0 failed (still 41/41 after steps 6 and 7) |

Smoke tests:
- **Circuit Studio** (`just studio`): the page loads. A **simulated ESP32** run streamed V/T/SOC/SOH live (about 2,700 good lines), and Stop worked. **Fault injection was not exercised:** the Dash fault dropdown would not open under browser automation (two attempts). Check it by hand.
- **Web Studio**: Analyze, then "Assess the demo pack". The decision card rendered (full engine: *Insufficient or untrustworthy data*, with the failed DQ checks listed).

## 5. Disposition mapping (step 6)

- `config/decision_map.json`: REUSE = `low_speed_ev`. REPURPOSE = `residential_storage`, `commercial_peak_shaving`, `telecom_backup`.
- `services/api/revive_api/disposition.py`: `disposition(decision, application)`. It matches on the prefix. For `Second-Life` it resolves the application key from the key, or from the workload label in `engines/ml/configs/workloads.yaml`. Any decision it does not know gives `NO_DECISION`.
- `services/api/revive_api/services/assess.py`: after the engine runs, the summary gets an extra `disposition` field (full and lite engines). The report and all existing fields are unchanged.
- `services/api/tests/test_disposition.py`: 5 tests, one per code.

## 6. Extras (step 7)

- **Web disposition chip:** done. `just sync-config` copies `config/decision_map.json` to `apps/web-studio/data/decision_map.json`. `assets/js/lib/disposition.js` uses the same prefix rules, and the Analyze page shows the chip above the report. Verified in the browser: the demo pack shows "No decision". `engines/*.js` untouched.
- **Reconcile web variants:** done.
  - Moved `lib/duckdb.js` and `tools/convert_db.py`.
  - `convert_db.py` wrote the storage-v1.0 copy to `apps/web-studio/data/db/revive_tery.duckdb`.
  - `app.js` now loads the demo tables through DuckDB-WASM and falls back to the CSVs in `data/demo/`. It sets `app.dbSource`, and the Database page banner shows that source.
  - Verified in the browser: "Loaded from the project database (DuckDB v1.1.1)". The demo assessment is identical to the CSV path.
  - `_reconcile_from_demo_front/` deleted.

## 7. Open items and doubts

1. **`just` and the apostrophe in the user path (`Nishanth's lap`).** `just` builds PowerShell commands like `C:\Users\Nishanth's lap\...\python.exe ...`, and the `'` breaks parsing. Workaround (no justfile change): set `REVIVE_PY` to the 8.3 short path, e.g. `$env:REVIVE_PY = "C:\Users\NISHAN~1\venvs\REVIVE~2\Scripts\python.exe"`.
2. **Port 8080 was already in use** by a server for the legacy `bulid X` folder that was running before this work. I left it alone. The web smoke tests used port 8081/8082 (`python -m http.server` in `apps/web-studio`).
3. **`just web-regen` was not run.** `export_assets.py` reads `engines/ml/data/processed/severson_windows.parquet`, which was deliberately not migrated (`just etl` in `engines/ml` regenerates it). The tools' paths are fixed, but the full regeneration is unverified.
4. **The old `pages/backend.js` (in-browser SQL backend page) was not ported.** It was used only as a reference, as instructed. The current `backend.js` page was left as is.
5. **The WASM DB copy includes 3,476 `test_run_log` rows** from the Circuit Studio smoke run. They are labelled SIMULATED. To ship a clean copy: `just db`, then `python apps/web-studio/tools/convert_db.py data/db/revive_tery.duckdb`.
6. **The stored `summary_json` in `assessments` now includes `disposition`.** It is part of the summary, not the report. The saved `report` is unchanged.
7. **`registry.json` was not edited** (no component path changed). `just impact engines/ml/configs/limits.yaml` lists the four web-studio regenerate steps.

## 8. Follow-up: multiple battery datasets

The database held only DEMO-EV-PACK-001. It now holds **7 synthetic packs** (`engines/database/make_demo_fleet.py`). Checked by assessing every pack with the full engine in Python and in the browser (same decisions): 001 No decision (its DQ checks fail by design), 002/003/004 Inspect (OOD gate quarantines the generated telemetry), 005/006 Recycle (safety triage), 007 Recycle (temperature limit breached). No pack reaches a Second-Life decision: the OOD filter flags the generated windows. Tuning the generator until one does was not attempted.
Changed: `battery_asset` gains an `asset_id` column and each consumer filters on it (listed in `engines/database/MODULE.md`); the Analyze page has a pack selector and "Assess all packs". Suites after the change: API 18 passed, ReLife 39 OK, web 41/41, `just check` 0 errors.


## 9. Follow-up: ML as the core intelligence

Added (nothing existing was replaced): `engines/ml/src/revive_ml/intelligence/` (mapper, identity, advisor, workflow), `engines/ml/configs/intelligence.yaml` and `battery_profiles.yaml`, `services/api/revive_api/{routes_intelligence.py, services/intelligence.py}` (+ 2 lines in `main.py`), tests `engines/ml/tests/test_intelligence.py` (15) and `services/api/tests/test_intelligence_api.py` (6). New tables: `ml_battery_profile`, `ml_suggestions`. Suites after: ML 104 passed, API 24 passed, `just check` 0 errors.
Not done: the web studio and Circuit Studio do not call the new endpoints yet (the web app is static JavaScript with no Python ML); the chemistry/maker weights are assumed priors.

## 10. Follow-up: ML in the web app

Analyze page: new "ML assistant: add a battery" card (backend upload, mapping table, needs form, advice). Circuit Studio: "ML suggestion" card after a test (simulated/hardware runs are sent as a table with their full readings; a database replay asks the backend about the stored pack). API: CORS now also allows any http://localhost or 127.0.0.1 port. ML fix found while testing: a single cell's voltage window is only a hint and never confirms chemistry (the ML asks). Verified in the browser against a scratch copy of the database; web 41/41, ML 105, API 24 passed.
Known: the engine's "stuck sensor" check flags simulator runs (voltage repeats at 3-decimal resolution), so a simulated run usually lands on "2 · fix the data"; the engine rule was not changed.
