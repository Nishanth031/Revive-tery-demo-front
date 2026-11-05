# apps/circuit-studio: Circuit Studio dashboard (Dash)

**Purpose:** live bench view: pick virtual / simulated / real ESP32 source, watch V/I/T, SOC/SOH gauges, fault banner, end-of-life decision; ML panel for uploads.
**Files:** `app.py` (layout + callbacks, port 8050) · `ml_panel.py` · `backend_connector.py`.
**Depends on (flat imports via PYTHONPATH):** `engines/bms`, `engines/lite`, `engines/database`; optional full engine via `pip install -e engines/ml`.
**Origin:** `bulid X/src/`. **Run:** `just studio` then open http://127.0.0.1:8050. **Test:** manual smoke (start, run the simulated source, inject a fault).
