# engines/lite: lite analyzer and upload bridge

**Purpose:** (1) read messy uploads (.csv/.xlsx/.zip), (2) triage by capacity when the full contract cannot be met, (3) convert DB rows/uploads/zipped bundles into the full engine's contract bundle.
**Files:** `ml_analyzer_suggester.py` (`BatteryFileExtractor`, `DuckDBSeeder`, `SecondLifeSuggester`, `ingest_and_suggest`) · `ml_engine_bridge.py` (`bundle_from_database/rows/zip`, `summarize_full`, `summarize_lite`, `AdapterError`).
**Public interface:** the function names above; `AdapterError` carries the reason an upload cannot be assessed by the full engine.
**Rule:** refuse with a reason instead of guessing missing timestamps/capacity.
**Imports are flat**; the platform adds `engines/lite` to `PYTHONPATH`. `ml_engine_bridge` needs `revive_ml` installed (`pip install -e engines/ml`).
**Origin:** `bulid X/src/`. **Port:** `apps/web-studio/assets/js/engines/{lite,contract}.js`.
**Test:** `just test-api`, `just test-web` (lite cases on the 7 sample files).
