# Graph Report - bulid X  (2026-11-04)

## Corpus Check
- Corpus is ~23,516 words - fits in a single context window. You may not need a graph.

## Summary
- 537 nodes · 1235 edges · 25 communities (19 shown, 6 thin omitted)
- Extraction: 94% EXTRACTED · 6% INFERRED · 0% AMBIGUOUS · INFERRED: 72 edges (avg confidence: 0.91)
- Token cost: 70,661 input · 0 output

## Community Hubs (Navigation)
- ML Engine Bridge & API Tests
- Circuit Studio Dashboard UI
- Lite Analyzer & Upload Ingest
- ML Analyzer Panel
- Backend Assessment Service
- Backend Docs & Dependencies
- Relational DB Build & Connector
- Upload & Bundle Endpoints
- Test Run Endpoints
- API Routes & Health
- Test Bench & Request Models
- Software ESP32 Simulator
- Battery Profiles & DB Access
- BMS Engine Core
- Run Controller
- Readings & DB Errors
- Backend Package & DB Door
- API Error Handlers & Events
- Serial Telemetry Parsing
- Assessment & Fault Requests
- Locked DuckDB Connections
- ESP32 Hardware Link
- Firmware Messages & Link Stats
- Telemetry Logging
- Read-only Serial Port

## God Nodes (most connected - your core abstractions)
1. `RunController` - 27 edges
2. `refresh()` - 19 edges
3. `BMSEngine` - 18 edges
4. `DatabaseUnavailable` - 17 edges
5. `assess_battery()` - 16 edges
6. `SimulatedESP32` - 16 edges
7. `DuckDBSeeder` - 16 edges
8. `list_battery_ids()` - 14 edges
9. `load_battery_profile()` - 14 edges
10. `SerialStats` - 13 edges

## Surprising Connections (you probably didn't know these)
- `Optional full ML engine install (revive-tery-ml, Python <=3.13)` --semantically_similar_to--> `Assessment engine selection (auto/full/lite)`  [INFERRED] [semantically similar]
  src/requirements.txt → backend/README.md
- `duckdb==2.0.0 (backend)` --semantically_similar_to--> `duckdb==2.0.0 (Circuit Studio)`  [INFERRED] [semantically similar]
  backend/requirements.txt → src/requirements.txt
- `lifespan()` --uses--> `DatabaseUnavailable`  [INFERRED]
  backend/revive_api/main.py → src/bms_engine.py
- `_db_down()` --uses--> `DatabaseUnavailable`  [INFERRED]
  backend/revive_api/main.py → src/bms_engine.py
- `_ingestion()` --uses--> `IngestionError`  [INFERRED]
  backend/revive_api/main.py → src/ml_analyzer_suggester.py

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **REVIVE-TERY API service layers** — backend_readme_revive_api, backend_readme_db_access_layer, backend_readme_runs_service, backend_readme_ingest_service, backend_readme_assess_service [EXTRACTED 1.00]
- **Full vs lite assessment engine fallback** — backend_readme_assess_service, backend_readme_full_ml_engine, backend_readme_lite_analyzer, backend_readme_engine_auto_fallback, src_requirements_optional_ml_engine [INFERRED 0.85]

## Communities (25 total, 6 thin omitted)

### Community 0 - "ML Engine Bridge & API Tests"
Cohesion: 0.05
Nodes (23): test_contract_bundle_zip_runs_the_full_engine(), test_simulated_run_fault_injection_and_stop(), test_stream_cursor_returns_only_new_readings(), test_timestamped_upload_reaches_the_full_engine(), test_upload_maps_columns_and_rejects_bad_types(), test_virtual_replay_run_and_conflict(), _upload(), _wait_not_running() (+15 more)

### Community 1 - "Circuit Studio Dashboard UI"
Cohesion: 0.07
Nodes (27): build_data_label(), build_decision_card(), build_fault_banner(), build_kpis(), build_profile_card(), build_status(), circuit_elements(), circuit_stylesheet() (+19 more)

### Community 2 - "Lite Analyzer & Upload Ingest"
Cohesion: 0.09
Nodes (12): ensure_tables(), ingest(), BatteryFileExtractor, BatterySpec, DuckDBSeeder, ExtractedFile, ingest_and_suggest(), IngestionError (+4 more)

### Community 3 - "ML Analyzer Panel"
Cohesion: 0.10
Nodes (24): analyze_uploads(), assess_database_battery(), _capacity_figure(), _database_battery_options(), _engine_status(), _error(), _files_for(), FormSpec (+16 more)

### Community 4 - "Backend Assessment Service"
Cohesion: 0.10
Nodes (22): read(), records(), seeder(), uploads_log(), SpecIn, assess_battery(), assess_bundle(), bundle_from_database() (+14 more)

### Community 5 - "Backend Docs & Dependencies"
Cohesion: 0.10
Nodes (20): services/assess (full ML engine or lite analyzer), Normalised assessment summary + provenance-tagged report, Zipped data-contract bundle assessment, db.py single DuckDB door (single writer, shared lock), Full ML engine (revive-tery-ml), services/ingest (.csv/.xlsx/.zip to ml_telemetry), Lite analyzer (capacity-based triage), REVIVE-TERY backend API (FastAPI) (+12 more)

### Community 6 - "Relational DB Build & Connector"
Cohesion: 0.13
Nodes (8): _fetch_asset(), _fetch_time_series(), get_battery_dashboard_data(), create_indexes(), load_tables(), main(), sql_string(), table_columns()

### Community 7 - "Upload & Bundle Endpoints"
Cohesion: 0.11
Nodes (7): assess_bundle(), upload(), save_uploads(), UploadTooLarge, client(), ml_examples(), samples()

### Community 8 - "Test Run Endpoints"
Cohesion: 0.16
Nodes (11): current_run(), inject_fault(), start_run(), stop_run(), RunStartIn, reading_dict(), RunConflict, set_fault() (+3 more)

### Community 9 - "API Routes & Health"
Cohesion: 0.15
Nodes (11): table_names(), battery_detail(), get_assessment(), health(), lifespan(), list_assessments(), list_batteries(), list_faults() (+3 more)

### Community 10 - "Test Bench & Request Models"
Cohesion: 0.16
Nodes (3): SimulationSettings, get_decision_for_ui(), get_secondary_use_case()

### Community 11 - "Software ESP32 Simulator"
Cohesion: 0.15
Nodes (3): open_circuit_voltage(), _quantise(), SimulatedESP32

### Community 12 - "Battery Profiles & DB Access"
Cohesion: 0.17
Nodes (5): BatteryProfile, list_battery_ids(), load_battery_profile(), open_db(), table_columns()

### Community 13 - "BMS Engine Core"
Cohesion: 0.17
Nodes (3): BMSEngine, calculate_soc(), calculate_soh()

### Community 15 - "Readings & DB Errors"
Cohesion: 0.23
Nodes (3): DatabaseUnavailable, Sample, VirtualBattery

### Community 17 - "API Error Handlers & Events"
Cohesion: 0.27
Nodes (7): _adapter(), _conflict(), _db_down(), _ingestion(), _not_found(), stream_run(), _too_large()

### Community 18 - "Serial Telemetry Parsing"
Cohesion: 0.24
Nodes (5): list_serial_port_details(), list_serial_ports(), _number(), parse_telemetry_line(), PortInfo

### Community 19 - "Assessment & Fault Requests"
Cohesion: 0.22
Nodes (5): create_assessment(), AssessIn, FaultIn, HardwareIn, SimulationIn

### Community 21 - "ESP32 Hardware Link"
Cohesion: 0.25
Nodes (4): HardwareError, open_esp32_port(), read_esp32_telemetry(), samples()

## Knowledge Gaps
- **5 isolated node(s):** `Normalised assessment summary + provenance-tagged report`, `GET /api/runs/stream (server-sent events)`, `Zipped data-contract bundle assessment`, `Sample panel settings (LFP, 16 in series, 100 Ah)`, `dash / dash-cytoscape / plotly`
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 186 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **6 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Lite analyzer (capacity-based triage)` connect `Backend Docs & Dependencies` to `Lite Analyzer & Upload Ingest`?**
  _High betweenness centrality (0.050) - this node is a cross-community bridge._
- **Are the 10 inferred relationships involving `RunController` (e.g. with `BatteryProfile` and `BMSEngine`) actually correct?**
  _`RunController` has 10 INFERRED edges - model-reasoned connections that need verification._
- **What connects `Normalised assessment summary + provenance-tagged report`, `GET /api/runs/stream (server-sent events)`, `Zipped data-contract bundle assessment` to the rest of the system?**
  _5 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `ML Engine Bridge & API Tests` be split into smaller, more focused modules?**
  _Cohesion score 0.053939714436805924 - nodes in this community are weakly interconnected._
- **Why does `SimulatedESP32` connect `Software ESP32 Simulator` to `Circuit Studio Dashboard UI`, `Test Bench & Request Models`, `Run Controller`?**
  _High betweenness centrality (0.048) - this node is a cross-community bridge._
- **Are the 2 inferred relationships involving `refresh()` (e.g. with `.load_initial_battery()` and `.snapshot()`) actually correct?**
  _`refresh()` has 2 INFERRED edges - model-reasoned connections that need verification._
- **Should `Circuit Studio Dashboard UI` be split into smaller, more focused modules?**
  _Cohesion score 0.06894049346879536 - nodes in this community are weakly interconnected._