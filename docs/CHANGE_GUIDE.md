# Change guide: "I want to edit X, what do I touch?"

Always finish with `just impact` (or `just check` for contracts). It lists what else to re-run.

| Edit | Edit these | Then run |
|---|---|---|
| ML thresholds, limits, costs, workloads | `engines/ml/configs/*.yaml` | `just test-ml`, `just web-regen` |
| A data-quality check | `engines/ml/src/revive_ml/dq/detectors.py` **and** `apps/web-studio/assets/js/engines/dq.js` | `just test-ml`, `just web-regen` |
| Gate / state / physics / economics logic | matching module in `engines/ml/src/revive_ml/<stage>/` + its JS port in `apps/web-studio/assets/js/engines/` | same |
| Retrain models | `just train train-gate` inside `engines/ml` | `just web-regen` (re-exports models, re-checks vs sklearn/MAPIE) |
| BMS maths (SOC/SOH, simulator, run control) | `engines/bms/*.py` + `bms.js` / `esp32sim.js` / `runController.js` | `just test-api`, `just web-regen` |
| ESP32 JSON line | `engines/firmware`, `contracts/esp32_line.schema.json`, `bms_engine.parse_telemetry_line`, `bms.js` | `just check`, `just test-api`, `just test-web` |
| Upload parsing / bridge | `engines/lite/*.py` + `lite.js` / `contract.js` | `just test-api`, `just web-regen` |
| Bundle metadata or telemetry columns | `contracts/*.schema.json` + `revive_ml/contract.py` + `ml_engine_bridge.py` + `contract.js`; bump `contracts/CHANGELOG.md` | `just check`, `just test-all` |
| API endpoint | `services/api/revive_api/` (+ `tests/`) | `just test-api` |
| Reuse/repurpose/recycle wording | `config/decision_map.json` | `just check` |
| A web page or the look | `apps/web-studio/assets/js/pages/*.js`, `ui/*.js`, `assets/css/app.css` | `just test-web`, open `just web` |
| ReLife prototype | `apps/relife-studio/*.py` (+ `relife.js` if an engine file) | `just test-relife` |
| New engine / app | new folder + `MODULE.md` + one `registry.json` entry | `just check` |

## Rules that never bend

1. Python is the source of truth for engines; JS ports follow and are proven by golden tests.
2. Never edit generated files by hand: `apps/web-studio/data/**`, `apps/web-studio/tests/golden/**`.
3. Every number keeps its provenance tag; never invent a missing value; never flip current sign.
4. Hardware stays monitor-only; synthetic data stays labelled synthetic.
5. One writer for DuckDB at a time.
6. Small commits: one concern per commit, run `just test-all` before the commit.

## Fleet, insight and firmware (since the upgrade)

| Edit | Edit these | Then run |
|---|---|---|
| Add or change packs | the user's DB (re-import) or `engines/database/csv_bundle/*.csv`; test cases in `import_fleet.py` `FLAWS` | `just db`, `just fleet`, `just web-db`, `just web-regen`, `python scripts/fleet_parity.py` |
| Dense telemetry generator | `engines/database/import_fleet.py` (never the data-quality rules) | same as above |
| Insight (reasons, confidence, what-if, plan) | `engines/ml/src/revive_ml/insight/*.py` + `assets/js/engines/insight.js`; weights in `configs/intelligence.yaml` | `just test-ml`, `just web-regen` |
| Tariff region, reuse valuation | `configs/economics.yaml` (source + URL + date, else PLACEHOLDER), `configs/workloads.yaml` `valuation_mode` | `just test-ml`, `just fleet`, `just web-regen` |
| Firmware | `engines/firmware/revive_tery_esp32/*.ino` (+ contract, bms_engine, esp32_sim, bms.js, esp32sim.js) | `just check`, `just fw-build`, `just wokwi-sync`, `just test-bms`, `just web-regen` |
| Circuit | `engines/firmware/wokwi/diagram.json` + `circuit_meta.json` | `just wokwi-sync`, `just check` |
| Fleet API | `services/api/revive_api/routes_fleet.py`, `services/fleet.py` | `just test-api` |
| Command Center / pack / live / history pages | `apps/web-studio/assets/js/pages/*.js`, `lib/fleet.js`, `ui/*.js`, `assets/css/pro.css` | `just test-web`, open `just web` |
