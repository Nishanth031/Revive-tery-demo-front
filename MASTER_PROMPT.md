# MASTER PROMPT: build the REVIVE-TERY Platform

> For **Claude Code, Opus 5.5, low effort**. Paste everything below the line into Claude Code, started inside this folder (`REVIVE-TERY-Platform`).
> Written for low effort: every step is explicit, ordered and checkable. Do not plan at length, do not redesign. Execute the steps in order.

---

You are finishing the **REVIVE-TERY Platform**, a clean home for five legacy projects built around this problem:

> *Give Used EV Batteries a Second Life: quickly assess the health of a used EV battery and decide whether it should be reused, repurposed or recycled (AI/ML, battery analytics, EV technology, predictive analytics).*

The scaffold, docs, contracts, registry, scripts and `justfile` already exist in this folder. Your job: bring the legacy code in, make every part run from its new place, prove it with the tests, and leave a short report. You are on Windows (PowerShell). The legacy folders sit next to this one (same parent, "Bulid X") and are **read-only** to you.

## 0. Hard rules (never break)

1. **Never modify, move or delete anything in the five legacy folders.** Only read and copy from them.
2. **Do not change engine logic or numbers.** Allowed edits are only: file paths, `sys.path`/`PYTHONPATH` handling, import locations, config path lookups, and the additive items in steps 6 and 7. No refactors, no renames, no reformatting.
3. Keep imports **flat** in `engines/bms`, `engines/lite`, `engines/database` (the `justfile` sets `PYTHONPATH`). Keep `engines/ml` layout as is.
4. Do not hand-edit generated files: `apps/web-studio/data/**`, `apps/web-studio/tests/golden/**`.
5. Product safety rules stay: hardware is **monitor-only** (never write to the ESP32); bench is low-voltage only; every number keeps its provenance tag (`measured | modelled | assumed | synthetic`); never invent a missing value; never flip current sign; synthetic data stays labelled synthetic.
6. The web app stays plain HTML + CSS + vanilla JS ES modules (no framework, no bundler, no TypeScript).
7. Put Python virtual environments **outside OneDrive**: `$HOME\venvs\...`.
8. Do not ask questions. If unsure, choose the option that touches the fewest files and write the doubt in `docs/MIGRATION_REPORT.md`.
9. If a test fails for a reason that is **not** a path/import problem, do not "fix" the logic: stop that suite, record the failure (test name + error), continue with the next suite.

## 1. Orient (5 minutes max)

Read: `README.md`, `registry.json`, `docs/CHANGE_GUIDE.md`, `docs/ARCHITECTURE.md`, every `MODULE.md`. Skim `docs/PROJECT_INVENTORY.md`. Do not read the legacy folders yet.
Check versions: `py -3.13 --version`, `node --version`, `git --version`. Python must be 3.13 (the ML engine is built on it).
Rename `justfile.txt` to `justfile` (`Rename-Item justfile.txt justfile`); it was shipped as .txt only because the transfer blocks the name `justfile`.
Run `git init` here if there is no repo, then `git add -A; git commit -m "scaffold: platform structure, contracts, registry, scripts"`.

**Done when:** you know the layout and the commit exists.

## 2. Migrate the code

```powershell
python scripts\migrate_from_legacy.py            # dry run, read the plan
python scripts\migrate_from_legacy.py --apply
python scripts\check_contracts.py
```
- The dry run must show **no MISSING sources**. If one is missing, look for the real path under the legacy base, fix `scripts/migration_manifest.json`, re-run. Do not copy by hand.
- After `--apply`, `check_contracts.py` must print `0 error(s)` (warnings are fine).
- Commit: `migrate legacy code into platform layout`.

**Done when:** `engines/ml/src/revive_ml`, `services/api/revive_api`, `apps/web-studio/assets/js/engines`, `apps/relife-studio/main.py`, `apps/circuit-studio/app.py`, `data/db/revive_tery.duckdb` all exist.

## 3. Environments

```powershell
py -3.13 -m venv $HOME\venvs\revive-platform
$py = "$HOME\venvs\revive-platform\Scripts\python.exe"
& $py -m pip install -U pip rust-just
& $py -m pip install -e "engines\ml[dev,api]" -r services\api\requirements.txt -r apps\circuit-studio\requirements.txt
py -3.13 -m venv $HOME\venvs\revive-relife
& "$HOME\venvs\revive-relife\Scripts\python.exe" -m pip install -r apps\relife-studio\requirements.txt
cd apps\web-studio; npm install; cd ..\..
$env:REVIVE_PY = $py
```
Wheels only; do not install compilers. If a package fails to install, record it and continue.

**Done when:** `& $py -c "import revive_ml, fastapi, dash, duckdb"` runs without error.

## 4. Fix paths (these edits only)

Make each of these resolve from the **platform** layout, with env vars winning over defaults (`REVIVE_DB`, `REVIVE_PLATFORM_ROOT`):

a. `services/api/revive_api/settings.py`: `APP_ROOT` becomes the platform root (`REVIVE_PLATFORM_ROOT` or three folders up from this file). Replace the single `SRC_DIR` insert with inserts for `engines/bms`, `engines/lite`, `engines/database`. Default `DB_PATH` = `data/db/revive_tery.duckdb` (still overridden by `REVIVE_DB`). Leave `bms_engine.DB_PATH = DB_PATH` as is.

b. `engines/bms`, `engines/database`, `engines/lite`, `apps/circuit-studio`: run
`Select-String -Path engines\*\*.py,apps\circuit-studio\*.py -Pattern 'data.database|csv_bundle|ml_samples|__file__|parents\['`
and fix every default location: database file -> `data/db/revive_tery.duckdb` (env `REVIVE_DB` first), CSV bundle -> `engines/database/csv_bundle`, samples -> `engines/database/ml_samples`, output of `make_ml_samples.py` -> `engines/database/ml_samples`. Compute from the file's own location (the platform root is two folders up from `engines/<x>/`, and from `apps/circuit-studio/`).

c. `apps/relife-studio`: its database search looks in its folder and up to three levels above. Add `data/db` (platform root) as a candidate. Nothing else.

d. `apps/web-studio/tools/*.py` and `tools/make_bundles.mjs`: they point at sibling legacy folders (`bulid X`, `revive-tery-ml`, `Hackathon project ev (3)`). Replace with platform paths: ML -> `engines/ml`, BMS/simulator/run controller/lite -> `engines/bms` and `engines/lite`, ReLife -> `apps/relife-studio`, database CSVs -> `engines/database/csv_bundle`, firmware -> `engines/firmware/revive_tery_esp32`, ML reports/models/configs/docs -> inside `engines/ml`. Define the platform root once at the top of each tool; change nothing else in the tools.

e. `engines/ml/src/revive_ml/paths.py`: **do not edit**; it resolves relative to `engines/ml` and should work. Just verify with `& $py -c "from revive_ml.paths import CONFIG_DIR; print(CONFIG_DIR.exists())"` (must print `True`).

Commit: `fix paths for platform layout`.

**Done when:** `just db` builds/opens the database, and `just api` starts and `http://127.0.0.1:8000/api/health` returns JSON (stop the server afterwards).

## 5. Run every test suite, in this order

```powershell
just check
just test-ml
just db
just test-api
just test-relife        # use the revive-relife venv: $env:REVIVE_PY="$HOME\venvs\revive-relife\Scripts\python.exe"
just test-web
```
Expected from the legacy docs: web parity **41 tests** pass; ML pytest passes (dataset-dependent tests are skipped); API pytest passes against a scratch DB copy.
For each suite record: command, pass/fail counts. Fix only path/import problems (rule 9).
Then smoke-test the apps: `just studio` (open http://127.0.0.1:8050, start the **simulated ESP32** source, inject a fault, stop), `just web` (open http://localhost:8080, open **Analyze**, press **Assess demo pack**, confirm a decision card renders), then stop both. Close the Dash app before starting the API (DuckDB has one writer).

Commit: `tests green` (or `tests: partial, see report`).

## 6. Reuse / repurpose / recycle mapping (additive, API only)

1. Open `engines/ml/configs/workloads.yaml`. List the workload keys and labels.
2. Fill `config/decision_map.json`: workload keys whose label is a vehicle/low-speed EV go to `application_keys_to_REUSE`; stationary-storage ones go to `application_keys_to_REPURPOSE`.
3. Create `services/api/revive_api/disposition.py` with `disposition(decision: str, application: str | None) -> {"code": ..., "label": ...}` reading `config/decision_map.json` (match by `match_prefix`; for `Second-Life` use the application key; default as in the file). Unknown decision -> `{"code": "NO_DECISION", ...}`.
4. Add `disposition` to the normalised `summary` returned by the assessment endpoints **after** the engine runs. Do not change the engine, the saved `report`, or any existing field.
5. Add `services/api/tests/test_disposition.py`: one test per code (REUSE, REPURPOSE, RECYCLE, INSPECT, NO_DECISION) using the exact decision strings: `Second-Life: <label>`, `Recycle`, `Reject (safety triage): route to recycling`, `Inspection required`, `Insufficient or untrustworthy data`.
6. `just test-api` and `just check` must pass. Commit: `add disposition mapping`.

## 7. Time-boxed extras (skip a bullet after one failed attempt and note it)

- **Web disposition chip:** add `just sync-config` (copies `config/decision_map.json` to `apps/web-studio/data/decision_map.json` — the one allowed hand-copied file) and show a Reuse / Repurpose / Recycle chip on the Analyze page's decision card, using the same prefix rules in a small `assets/js/lib/disposition.js`. Do not touch `engines/*.js`. `just test-web` must stay green.
- **Reconcile the two web variants:** `apps/web-studio/_reconcile_from_demo_front/` holds DuckDB-WASM pieces from the other variant. Move `assets/js/lib/duckdb.js` and `tools/convert_db.py` into `apps/web-studio`, and put the WASM-readable database at `apps/web-studio/data/db/revive_tery.duckdb`. Use the old `pages/database.js` and `pages/backend.js` only as reference to load the database in the browser, with CSV fallback in `data/demo/`. When it works and `just test-web` is green, delete `_reconcile_from_demo_front/`. If it does not work in two attempts, leave the folder and say so.

## 8. Finish

1. Edit `registry.json` only if a path changed. Run `just impact engines/ml/configs/limits.yaml` and check that it lists `web-studio` regeneration steps.
2. Write `docs/MIGRATION_REPORT.md`: what was copied, every path edit (file + one line), each suite with pass/fail counts, items skipped or failing with their error text, and anything you were unsure about.
3. `git add -A; git commit -m "migration report"`.
4. Print a final summary of at most 12 lines: suites passed/failed, apps smoke-tested, open items.
