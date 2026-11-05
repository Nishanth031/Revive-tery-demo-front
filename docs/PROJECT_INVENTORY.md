# REVIVE-TERY: Engines and Software Inventory

What has been built across the five folders in `Bulid X/`, mapped to the problem statement.

> **Problem statement: Give Used EV Batteries a Second Life.**
> Build a solution that can quickly assess the health of a used EV battery and determine whether it should be **reused, repurposed or recycled**.
> Tags: AI/ML · Battery Analytics · EV Technology · Predictive Analytics

Everything below was read from the code and docs in the five folders (inventory date 2026-11-05).
All project data is **synthetic or simulated**; results show the pipeline works, not anything about a real battery.

---

## 1. The five folders at a glance

| Folder | What it is | Language | Role in the solution |
|---|---|---|---|
| `bulid X` | Desktop toolkit: **Circuit Studio** (Dash), **FastAPI backend**, BMS engine, ESP32 simulator, DuckDB database, **ESP32 firmware**, lite ML analyzer | Python 3.13, C++ (Arduino) | Collects battery data (bench / simulated / replay), stores it, serves it, runs assessments |
| `revive-tery-ml` | Standalone **ML decision engine** (data quality → safety gate → state/RUL → physics projection → economics) | Python 3.13 | The brain: decides Second-Life vs Recycle vs Inspect vs "data not trustworthy" |
| `Hackathon project ev (3)` | **ReLife BMS Studio**: PySide6 desktop prototype (virtual adapters, scenarios, 30 s pulse test, battery catalog) | Python 3.11+ | Early screening / BMS-design prototype |
| `Revive-tery-demo-front` | **Web Studio, variant A**: every engine ported to browser JS, 11 pages, DuckDB-WASM database, built-in backend page | HTML/CSS/JS (ES modules) | Demo front end, no server needed |
| `revive-tery-web` | **Web Studio, variant B**: same app, later edit, pages merged (Data Quality Lab has 4 tabs), no DuckDB-WASM | HTML/CSS/JS (ES modules) | Demo front end (most recently edited) |

Variants A and B have diverged. See section 6 for the reconciliation decision.

---

## 2. Engines (the computation)

### Engine 1: ESP32 hardware + firmware  (`bulid X/firmware/revive_tery_esp32/`)
- ESP32 Dev Module reads **INA219** (I²C: SDA GPIO21, SCL GPIO22; 0.1 Ω shunt; 26 V / 3.2 A range) and **DS18B20** (1-Wire GPIO4, 4.7 kΩ pull-up).
- Prints one JSON line per second at 115200 baud: `{"voltage":3.712,"current":0.5210,"temperature":28.44}`; `#` lines are firmware messages (ready, wiring fault, OVER 26 V).
- **Monitor-only**: never reads serial, drives no outputs. Low-voltage bench use only.

### Engine 2: BMS engine  (`bulid X/src/`: `bms_engine.py`, `esp32_sim.py`, `run_controller.py`, `test_bench.py`)
- `bms_engine.py`: battery profile loading from DuckDB, **coulomb-counting SOC**, **SOH from usable capacity** (with stated basis), read-only serial port, telemetry line parser, serial link statistics, tier rule, telemetry logger.
- `esp32_sim.py`: **software ESP32** with cell OCV/thermal model, INA219/DS18B20 quantisation and noise, **fault injection**.
- `run_controller.py`: orchestrates three sources: **virtual replay** (recorded DB telemetry), **simulated ESP32**, **real ESP32** (serial). Thread-safe snapshot for the UIs.
- `test_bench.py`: request models and bench helpers.

### Engine 3: Lite analyzer + upload adapter  (`bulid X/src/`: `ml_analyzer_suggester.py`, `ml_engine_bridge.py`)
- `BatteryFileExtractor`: reads `.csv/.xlsx/.zip`, header aliasing; `DuckDBSeeder` stores uploads as `ml_telemetry`.
- `SecondLifeSuggester`: capacity-based triage when data cannot meet the full contract (no timestamps etc.): simple gate, resistance proxy, SOH from last 5 cycle capacities, linear fade, second-life vs recycle suggestion.
- `ml_engine_bridge.py`: converts DB rows / uploads / zipped bundles into the full engine's data contract; `summarize_full` / `summarize_lite` normalise results for UI cards. Refuses with reasons rather than guessing.

### Engine 4: Full ML engine  (`revive-tery-ml/src/revive_ml/`)
Pipeline `pipeline.assess(bundle)`:

| Stage | Module(s) | What it does |
|---|---|---|
| Contract | `contract.py`, `convert.py`, `synth.py` | pydantic metadata + pandera telemetry schema; demo-CSV converter (explicit mapping, never guesses); synthetic clean-bundle generator |
| 1. Data quality | `dq/detectors.py`, `readiness.py`, `inject.py`, `validate.py` | **14 detectors** (sample size, provenance, timestamps, sign convention, charge balance, regen sign, resistance, nulls, dropouts, stuck, spikes, range, missing temperature, SOH disagreement) → READY / READY_WITH_WARNINGS / NOT_READY. Fault injector + validation on 100 synthetic bundles |
| 2. Safety gate | `gate/limits.py`, `ood.py`, `features.py`, `train.py` | Datasheet limits → **Reject**; **IsolationForest** OOD/sensor-noise filter or open HIGH events → **Quarantine**; else **Pass** ("UL 1974-style triage", not certification) |
| 3. State | `state/estimate.py`, `features.py`, `train.py`, `etl_*.py`, `download.py` | SOH from latest capacity test; **HistGradientBoosting + MAPIE CV+** remaining-useful-life with interval (trained on Severson LFP; NASA PCoE ETL) |
| 4. Physics projection | `physics/fade.py`, `sanity.py` | Double-exponential fade, temperature/DoD/C-rate stress factors, calendar ageing, **1,000-draw Monte Carlo** per workload |
| 5. Economics | `econ/router.py`, `sensitivity.py` | Recycle metal value vs discounted second-life value (capped at buy-new cost) per application; decision + rationale; price-sensitivity sweep |
| Support | `provenance.py`, `config.py`, `paths.py`, `cli.py`, `api.py` | Provenance tags (measured/modelled/assumed/synthetic), YAML config, `revive-ml` CLI, optional `/assess` API |

Outputs of a run: **Second-Life: <application>**, **Recycle**, **Inspection required**, **Reject (safety triage)** or **Insufficient or untrustworthy data**, plus a comparison with the old SOH rule (>80 % stationary, 60–80 % low-speed EV, <60 % recycle).

Artifacts: `models/*.joblib` (state RUL, two gate OOD filters), `configs/*.yaml` (limits, dq_rules, physics, economics, workloads, datasets), `reports/*.json` (validation), `docs/model_cards/`.

Key measured results (from `reports/`): RUL gradient boosting RMSE 169 cycles / MAPE 16.6 % on 128 Severson cells (GroupKFold by cell); CV+ 90 % interval coverage 91.5 %; DQ detectors 15 of 16 fault types at 100/100, 0 false positives; physics sanity 6/6.

### Engine 5: Database  (`bulid X/database/`, `bulid X/src/build_relational_db.py`)
- **DuckDB** `revive_tery.duckdb`, built from `csv_bundle/` (8 tables: `battery_asset`, `modules`, `charge_sessions`, `telemetry`, `health_history`, `safety_events`, `materials_recycling`, `data_sources`) plus runtime tables `ml_telemetry`, `ml_ingest_log`, `test_run_log`, `assessments`.
- `make_ml_samples.py` generates 7 synthetic upload samples (`database/ml_samples/`).
- DuckDB allows **one writer**: close Circuit Studio before the API.

### Engine 6: ReLife BMS engine  (`Hackathon project ev (3)/Hackathon project ev/`: `bms_engine.py`, `models.py`, `battery_details.py`, `circuit_studio.py`, `database.py`)
- Battery profile + virtual hardware adapter (e.g. `V-LI-3-16`, `V-HV-PACK`) → compatibility check → scenario evaluation (Normal, Undervoltage, Overvoltage, Overcurrent, High temperature, Stale sensor) → **30 s virtual pulse test** → screening summary. Impedance-proxy SOH. Catalog of 23 research dataset records. Always labelled simulation only.
- Note: this `bms_engine.py` is a **different file** from Circuit Studio's `bms_engine.py`. Do not merge them.

### Engine 7: Browser engines  (`revive-tery-web/assets/js/engines/`, same set in `Revive-tery-demo-front`)
Line-by-line JS ports, checked against Python golden outputs (41 tests):
`pipeline.js`, `contract.js`, `dq.js`, `gate.js`, `state.js`, `physics.js`, `econ.js`, `lite.js`, `bms.js`, `esp32sim.js`, `runController.js`, `relife.js`, plus `samplePacks.js`. Support libs: `lib/np.js` (numpy/pandas behaviour), `csv.js`, `provenance.js`, `md.js`, `duckdb.js` (variant A only).

---

## 3. Software (applications and services)

| Software | Location | Stack | What the user does with it |
|---|---|---|---|
| **Circuit Studio** | `bulid X/src/app.py`, `ml_panel.py`, `backend_connector.py` | Dash + Plotly, :8050 | Start virtual/simulated/real runs, watch live V/I/T, SOC/SOH gauges, end-of-life decision, ML analyzer panel for uploads |
| **Backend API** | `bulid X/backend/revive_api/` | FastAPI + uvicorn, :8000, pytest suite | Batteries, runs (+SSE stream), uploads, assessments (`auto/full/lite`), read-only to hardware |
| **ReLife BMS Studio** | `Hackathon project ev (3)/.../` (`main.py` + 5 page modules) | PySide6, unittest suite | Overview, pack data import, battery catalog, circuit studio, 30 s test bench |
| **REVIVE-TERY Web Studio** | `revive-tery-web/`, `Revive-tery-demo-front/` | Static HTML + ES modules, JSZip, SheetJS, Web Serial | Analyze batteries, DQ lab, physics, economics, database, model evidence, ReLife, hardware, backend connector |
| **ML CLI / API** | `revive-tery-ml` (`revive-ml`, `just` targets) | Typer, FastAPI | `assess`, `download`, `etl`, `train`, `train-gate`, `validate-dq`, `physics-check`, `sweep`, `demo` |
| **Asset/test tooling** | `*/tools/` | Python + Node | `export_assets.py` (models → JSON, verified vs sklearn/MAPIE), `make_golden.py`, `make_bundles.mjs`, `convert_db.py` (DuckDB v2 → WASM-readable v1) |
| **Code knowledge graph** | `bulid X/graphify-out/` | graphify output | `GRAPH_REPORT.md`, `graph.html`: navigation aid only |

---

## 4. How this answers the problem statement

| Requirement | Where it is delivered |
|---|---|
| **Quickly assess health** | Live SOH/SOC from the BMS engine (seconds); capacity-test SOH + RUL from the ML engine; lite analyzer for messy uploads |
| **Reuse / repurpose / recycle** | Gate + economics router. Mapping used by this platform (interpretation, editable in `config/decision_map.json`): **Reuse** = Second-Life in a low-speed EV, **Repurpose** = Second-Life in stationary storage, **Recycle** = Recycle or Reject; plus **Inspect** and **No decision (bad data)** |
| **AI/ML** | HistGradientBoosting + MAPIE CV+ (RUL), IsolationForest (gate OOD) |
| **Battery analytics** | 14 data-quality detectors, BMS SOC/SOH, safety events |
| **Predictive analytics** | Remaining cycles with interval, SOH-per-year projection with Monte Carlo band, economics sensitivity |

## 5. Known gaps (from the projects' own docs)

1. **No real-battery validation.** All pack data is synthetic; public data are single lab cells (Severson LFP, NASA 18650).
2. **Distribution shift.** RUL model trained on new LFP cells; the NMC demo pack always triggers an out-of-distribution warning.
3. **Economics inputs are PLACEHOLDERs** (second-life energy value, refurbishment, logistics, payable fractions). Decisions near break-even can flip.
4. The "reuse vs repurpose vs recycle" wording is not a first-class output of the engines yet; it is a mapping on top of "Second-Life: <application>" / "Recycle".
5. Gate limits act on pack-average cell voltage (a weak cell can hide); IsolationForest is a noise/OOD screen, not a fault detector.

## 6. Things to know before building on this

- **Two web variants** (A `Revive-tery-demo-front`, B `revive-tery-web`) overlap about 90 %. Platform decision: **B is the base** (latest edit); port from A only `lib/duckdb.js`, the DuckDB-WASM database/backend pages and `tools/convert_db.py`.
- **Two different `bms_engine.py`** files exist (Circuit Studio vs ReLife). Keep separate.
- **Flat imports**: Circuit Studio and the backend import `bms_engine`, `ml_engine_bridge` etc. as top-level modules via `sys.path`. Keep them flat and fix paths, do not rewrite imports.
- **Path assumptions**: `revive_ml/paths.py` and `revive_api/settings.py` compute roots from their own location; both need care when moved.
- `data/processed/*.parquet` (~90 MB) and `.duckdb` pre-cleanup backups are regenerable or stale: not migrated.
- `Hackathon project ev` is a git repo with branches `main` and `bms-engine`.
- Raw dataset downloads (8+ GB) live outside the repo (`REVIVE_ML_CACHE`, default `%LOCALAPPDATA%\revive-tery-ml\cache`) because the folder is in OneDrive.
