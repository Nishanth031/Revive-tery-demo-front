# REVIVE-TERY Studio (web)

A static website that runs every REVIVE-TERY engine in the browser. There is no server or build step, and nothing is uploaded. Deploy it on GitHub Pages as is.

> All REVIVE-TERY data in this app is **synthetic** or simulated. Results show that the pipeline works; they say nothing about a real battery. The safety gate is **UL 1974-style triage**: a screening step, not UL certification or a safety approval.

## What's inside

| Page | Engine (original Python) |
|---|---|
| Circuit Studio | `bulid X/src`: `bms_engine`, `esp32_sim`, `test_bench`, `run_controller`. Virtual replay, the simulated ESP32 with fault injection, and a real ESP32 over Web Serial (read-only) |
| Analyze batteries | `ml_analyzer_suggester` (lite analyzer), `ml_engine_bridge` (upload adapter), `ml_panel` flow, plus the full engine |
| Data-quality lab | `revive-tery-ml`: contract, 14 data-quality detectors and readiness rules, gate, state, physics, economics, pipeline |
| Physics projection | `revive_ml.physics.fade` (double-exponential fade, stress factors, calendar ageing, 1,000-draw Monte Carlo) |
| Economics | `revive_ml.econ.router` and `econ.sensitivity` |
| Database | the eight demo tables; uploads (`ml_telemetry`, `ml_ingest_log`), `test_run_log` and assessment history, stored in this browser |
| Model evidence | the ML engine's validation reports and model cards |
| ReLife BMS Studio | `Hackathon project ev`: `bms_engine`, `models` (adapters, scenarios, 30 s virtual pulse test) |
| Firmware & hardware | `firmware/revive_tery_esp32.ino`, wiring and line protocol |
| Backend connector | read-only calls to the local FastAPI backend (`backend/revive_api`) |

The trained models (HistGradientBoosting + MAPIE CV+ for remaining life, and IsolationForest for the gate) are exported to JSON by `tools/export_assets.py`. The export checks the browser's algorithm against scikit-learn and MAPIE before writing anything.

## Tested against the Python engines

`tools/make_golden.py` records what the Python engines output. `npm test` then checks the JavaScript ports against those outputs (41 tests):

- all 23 full-pipeline cases (the demo pack, clean LFP/NMC packs, gate cases and every injected data-quality fault): decisions, every check status and message, gate window counts, remaining-life intervals, projections and economics;
- the exported models to 1e-9;
- the physics sanity tables and the price-sensitivity sweep;
- the lite analyzer and upload adapter on the 7 sample files;
- the BMS engine reading by reading;
- the simulated ESP32's line sequence;
- ReLife compatibility, evaluation, pulse test and screening.

```bash
npm install
```

```bash
npm test
```

## Run locally

Browsers block ES modules from `file://`, so serve the folder:

```bash
python -m http.server 8080
```

Then open http://localhost:8080.

## Deploy on GitHub Pages

1. Push this folder to a GitHub repository, either as the repository root or as a `docs/` folder.
2. Go to **Settings → Pages → Build and deployment**, choose **Deploy from a branch**, then pick the branch and folder (`/ (root)` or `/docs`).
3. The site is published at `https://<user>.github.io/<repo>/`. `.nojekyll` is included, so files are served as they are.

The site uses hash routing (`#/analyze`), so no server rewrite rules are needed. The hardware page's Web Serial access needs Chrome or Edge on a desktop. GitHub Pages serves over https, which Web Serial requires.

## Regenerating data

These steps need the `revive-tery-ml` virtual environment and the sibling folders `bulid X`, `revive-tery-ml` and `Hackathon project ev (3)`:

```bash
../revive-tery-ml/.venv/Scripts/python.exe tools/export_assets.py
```

```bash
../revive-tery-ml/.venv/Scripts/python.exe tools/make_golden.py
```

```bash
node tools/make_bundles.mjs
```

## Layout

```
index.html                 app shell
assets/css/app.css         styles (light and dark)
assets/js/app.js           router, shared state, asset loading
assets/js/engines/         the ported engines (no DOM; also imported by the Node tests)
assets/js/pages/           one module per page
assets/js/ui/              DOM helpers, SVG charts, report renderer
assets/js/lib/             numerics (numpy/pandas behaviour), CSV, provenance, markdown
assets/vendor/             JSZip 3.10.1 (MIT) and SheetJS 0.18.5 (Apache-2.0), with licences
data/                      configs, exported models, demo tables, samples, reports, docs, firmware
tests/                     Node parity tests and golden outputs
tools/                     export and golden-output scripts
```

## Safety

- The hardware connection is **monitor-only**: the serial wrapper can only read. DTR/RTS are held low so the board doesn't reset.
- The bench is **low-voltage only**. The INA219 is rated to 26 V.
- No value is invented. Missing timestamps, capacity or temperature are reported, and the engine falls back or refuses with a reason.
