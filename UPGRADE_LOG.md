# UPGRADE_LOG

## FINAL REPORT (2026-11-05, branch `upgrade/maximize`)

**What changed, per phase**
- **P0:** branch, log and baseline (all green: check 0 errors, ML 105, API 24, web 41, ReLife 39).
- **P1:** the user's own 60-pack database imported (`import_fleet.py`, run by `just db`), plus 4 platform packs and 6 labelled test cases = 70 packs. The original 12-row telemetry is kept unchanged; `telemetry_dense` (SYNTHETIC, 1,020 rows per pack) is generated from each pack's registry and capacity tests. NCA label mapped. Added `fleet_reports`, views, `just web-db` and `test_fleet.py`.
- **P2:** `revive_ml.insight` (reasons, heuristic confidence, what-if, break-even, robustness, next actions, rule gap, fleet plan, impact, passport). Region tariff (one sourced region). `low_speed_ev` valued as the avoided new pack. JS port with 23 golden parity cases. Contracts v1.1 plus a passport schema.
- **P7:** Command Center (default route), pack detail with live what-if, Live assessment, History, guided demo and a dark design system. The database loads lazily: the fleet table renders in about 0.3 s.
- **P5:**
  - Firmware v1.1.0: averaging, CRC, seq, ambient, watchdog, I2C bus-clear, throttled warnings.
  - Circuit: fuse, switch, decoupling and an ambient DS18B20.
  - Wokwi project, with `diagram.json` as the single source of truth for the circuit.
  - Realistic circuit view, the monitor-only guard and the circuit design rules.
- **P6:** fleet API (`/api/fleet`, summary, plan, refresh, battery, history, passport, what-if, meta, history lists).
- **P8:** architecture, change guide, judge Q&A, `DEMO_SCRIPT.md`, `RECORD_BACKUP.md`, `HARDWARE_DEMO.md` and module docs.
- **P9:** full rebuild, every suite, parity and a browser click-through with the API both running and stopped (all below).

**Fleet result:** 70 packs: the user's own 60 (github.com/Nishanth031/revive-tery-DB), 4 platform packs and 6 test cases, all SYNTHETIC. The engine's real counts with dense telemetry, identical in Python and JS (70/70 per pack):

| Disposition | Packs | From engine decisions |
|---|---|---|
| Repurpose | 25 | Second-Life 25 |
| Recycle | 24 | Recycle 21 + Reject (safety) 3 |
| Inspect | 15 | Inspection required 15 |
| No decision | 6 | Insufficient data 6: exactly the six test cases, each failing its own check |
| Reuse | 0 | — |

The user's 60 alone: Repurpose 23, Recycle 23, Inspect 14. With the original 12 rows instead: No decision 56, Inspect 12, Recycle 2.

**Test results (final run):**

| Suite | Result |
|---|---|
| `just check` | 0 errors; monitor-only 0 violations; circuit rules 0 failures |
| ML | 117 passed |
| DB | 9 passed |
| BMS / firmware lines | 8 passed, 1 skipped (no Wokwi capture) |
| API | 31 passed |
| ReLife | 39 OK |
| Contract guard | 1 passed |
| Web (`npm test`) | 80/80 |
| Fleet parity | 70/70 |
| 23-bundle Python/JS parity | holds; every reference decision unchanged |

**Decisions changed by the economics fix:** none. The 23 reference bundles and all fleet decisions are unchanged. Only `low_speed_ev` net values moved (clean LFP -735 -> -1,178 USD; clean NMC -497 -> -1,749 USD) under the avoided-new-pack valuation. Reuse still never wins: it earns 108/8 = 13.5 USD per usable kWh a year versus 15.7 for capped stationary storage, which also lasts longer. Reported, not forced.

**Firmware and circuit:**
- **Sketch:** v1.1.0 adds new line fields `ambient`, `seq`, `t_ms` and `crc` (CRC-8 0x07; the prompt's example line has the real CRC `8C`), plus `# fw=`, `# hb`, `# boot` and `# ds18b20` info lines and `(x<n>)` repeat counts.
- **Circuit:** fuse, manual switch, 100 nF ×2, 10 µF (conditional), I2C pull-ups (conditional) and an ambient DS18B20.
- **Wokwi files:** `diagram.json`, `circuit_meta.json`, `wokwi.toml`, `libraries.txt`, the INA219 custom chip sources and six scenarios.
- **Verified:**
  - Compiled with arduino-cli and esp32 core 3.3.12, both profiles.
  - Wokwi part types `wokwi-ds18b20`, `wokwi-resistor`, `board-esp32-devkit-c-v4` and the file formats were confirmed from the docs.
- **NOT verified:**
  - Flashing and any real hardware.
  - Measured power savings.
  - The custom chip build: no wasm toolchain here.
  - Any Wokwi run, lint or scenario: no wokwi-cli here.
  - The ESP32 board pin names in Wokwi: no docs page.
  - The chip's `controls` fields.
  - Iframe embedding: none documented, so the web card only offers a link and a zip download.

**Skipped or failed, and why:**
- **P3** (BMS alert engine, OCV recalibration, fault presets) and **P4** (lite readiness report and mapping preview) were NOT done: they are last in the priority order and ran out of time. The bench uses the existing fault injections, and its "alert timeline" lists the firmware fault messages the BMS engine classified.
- **P2.10:** NASA non-LFP validation not attempted (time box); "Known limits" added to the model card instead.
- **State-model export:** the Severson parquet was never migrated, so `export_assets` keeps the previous verified export (the model is unchanged).
- **Tariff regions:** India stays PLACEHOLDER (no sourced INR->USD rate or spread).
- **Not built:** Playwright (not installed, so the click-through used the built-in browser) and wokwi-cli (not installed).
- **Dash Circuit Studio** still draws from its own constants.
- **Console:** with the API stopped, the only error is the browser's `ERR_CONNECTION_REFUSED` from the Live-API probe.
- **DuckDB-WASM** (CDN) is now opt-in (`?duckdb=1`), so by default the web app makes no external request.

**Commands to run the demo:** `just db && just web-db && just web-regen && just api` and `just web`.
On this machine, set `REVIVE_PY` to the 8.3 short path first: the apostrophe in the user folder breaks `just`'s quoting. Stop the API before `just db` or `just web-db`, because DuckDB allows one writer.

---

Working log for MASTER_PROMPT_UPGRADE.md. One line per decision.

## P0 Baseline (2026-11-05)

- Branch `upgrade/maximize` created from `master` (HEAD bf8ecc5).
- Baseline: `just check` 0 errors / 0 warnings; ML pytest 105 passed; API pytest 24 passed; web `npm test` 41/41; ReLife unittest 39 OK; `tests/` contract guard 1 passed.
- Decision: `just test-all` runs `test-relife` with `REVIVE_PY`; ReLife needs its own venv (PySide6), so suites are run one by one with the right interpreter (platform venv for check/ml/api, relife venv for relife).
- Decision: `REVIVE_PY` is set to the 8.3 short path (`C:\Users\NISHAN~1\venvs\REVIVE~2\Scripts\python.exe`) because the apostrophe in the user folder breaks `just`'s PowerShell quoting (known since the migration).
- Decision: untracked `Claude outputs/` (the user's folder) added to `.git/info/exclude` so commits never pick it up.
- Tools found: `arduino-cli` present (`C:\Program Files\Arduino CLI`); scipy 1.18.1 present; Playwright NOT installed (smoke screenshots will use the built-in browser instead); `wokwi-cli` NOT installed.
- Pages: the web app was last loaded on 2026-11-05 with every page rendering (Overview, Circuit Studio, Analyze, DQ Lab, Database, Model evidence, ReLife, Hardware, Backend); a full click-through is repeated in P9.
- Note: a server from before this work is still on port 8080 (serves the legacy `bulid X` folder); left alone. My servers: API :8000 and web :8090.

## P1 Database and the 60-pack fleet

- Source: the user's repo cloned to `../_import/revive-tery-DB` (outside the repo), `revive_tery.duckdb` opened read-only; the pre-cleanup backup ignored. Layout matched the prompt (60 registry rows; 12 telemetry rows per pack, +05:30; 31 NMC / 21 LFP / 8 NCA).
- Decision (id conflicts): DEMO-EV-PACK-001, -003, -006 exist in both. The platform's 003/006 were different synthetic batteries (my earlier make_demo_fleet packs), so the user's database wins entirely for those ids (registry, battery_asset AND capacity history/telemetry/events). Reason: rule "do not replace its capacity histories"; keeping platform child rows under the user's specs would mix two batteries.
- Kept platform-only packs: DEMO-EV-PACK-002, DEMO-EV-PACK-007, DEMO-LFP-PACK-004, DEMO-LFP-PACK-005 (registry rows built from their own battery_asset; application/lifecycle_status left empty, not invented).
- NCA: added `"NCA (nickel cobalt aluminium)": "NCA"` to `revive_ml/convert.py` and `contract.js` (the only two maps; bms_engine/bridge/ReLife pass the label through). Unknown labels still raise (tested in Python and JS).
- Densifier (`import_fleet.py`, table `telemetry_dense`, SYNTHETIC): uses `revive_ml.synth` physics parameterised per pack. Two generator bugs found and fixed before trusting results: (a) CC charging overshot the pack's max voltage on 11 packs -> added CC-CV taper / BMS derate at the pack's own window; (b) cooling was fixed at 25 W/K for every pack size, so large ESS packs read >85 degC (`sensor_range`) -> cooling now scales with capacity like the heat capacity. No data-quality rule was touched.
- Test cases: first versions of DEMO-FLAW-01 (whole-record sign flip) and -02 (30-min gap) passed the checks: a consistent flipped convention is legitimately inferred, and 30 min is under the 20 %-of-span gap rule. Changed to a mid-record flip and a 60-min gap; now each flaw fails exactly its own check (01 sign_convention+regen_sign, 02 timestamps, 03 sensor_stuck, 04 sensor_spikes, 05 sensor_nulls+dropouts, 06 charge_balance+estimate_disagreement).
- Engine result, 70 packs, ORIGINAL 12-row telemetry: Insufficient data 50, Inspection 12, Reject 2, error 6 (the test cases have no original rows) -> dispositions NO_DECISION 56, INSPECT 12, RECYCLE 2. Matches the prompt's baseline character.
- Engine result, 70 packs, DENSE telemetry (Python): Second-Life 25, Recycle 21, Inspection 15, Reject 3, Insufficient 6 -> REPURPOSE 25, RECYCLE 24, INSPECT 15, NO_DECISION 6, REUSE 0. The user's 60: REPURPOSE 23, RECYCLE 23, INSPECT 14. JS port (tools/make_fleet_reports.mjs): identical counts and 70/70 per-pack parity (scripts/fleet_parity.py).
- Note: DEMO-ESS-PACK-007/011 are safety Rejects (temp_max_c 69.7/62.0 degC). Driven by the user's recorded pack resistance (up to 223 mOhm) under the generator's ASSUMED 0.5C charge profile: a modelled consequence, not a recorded event. DEMO-LFP-PACK-005: resistance ratio 2.05 > 2.0.
- Note: 14 Inspect packs: 9 are OOD quarantines (mostly small 2W/3W packs, 11-21 of 101 windows flagged; the gate was trained on 96s-style synthetic packs), 6 have an open HIGH-severity safety event in the user's data. Not tuned.
- No REUSE: structural (low_speed_ev valued like stationary storage and capped by buy-new); P2.4 addresses the valuation. Per 1.f, EXTRA packs are deferred until after P2.4, since no pack spec can produce REUSE under the current valuation.
- Registry rule vs engine: agrees 1, disagrees 59, no status 10 (stored per pack in fleet_reports.rule_agrees/rule_reason). Mostly IN_SERVICE packs the engine routes to Repurpose or Recycle, and SECOND_LIFE_CANDIDATE packs it recycles on economics.
- `just db` = import_fleet.py; new `just fleet`, `just web-db`, `just test-db`; `web-regen` now also runs `make_fleet_reports.mjs`. `export_assets.py` skips the state-model export when the Severson parquet is missing (it was never migrated) and keeps the previous verified export; the model is unchanged.
- Golden demo cases now select DEMO-EV-PACK-001 explicitly (make_golden.py); the demo tables hold the whole fleet.
- Tests: test_fleet.py 9 passed; API 25 passed (demo refusal test now asks for `telemetry_source: original`; advise test uses real fleet outcomes); web 43/43 (new fleet_db.test.mjs); ML and ReLife unchanged green.

## P2 ML insight layer and economics fixes

- New package `engines/ml/src/revive_ml/insight/` (explain, confidence, whatif, voi, fleet_opt, impact, passport, workflow). `pipeline.py` behaviour unchanged; `assess(..., region=None)` is an additive argument. New report content is the additive `insight` key.
- Reasons cite only report fields (test resolves every `metric` path). Ranking uses a fixed documented impact order, not a model.
- Confidence: heuristic (weights in `configs/intelligence.yaml` `confidence`), labelled "heuristic". Fleet: High 26, Medium 27, Low 17 (every NO_DECISION pack is Low).
- Break-even (known facts reproduced): tariff flips Recycle -> Second-Life at 0.0741 (clean LFP) and 0.0699 USD/kWh (clean NMC), inside the stated 0.06-0.08; NMC flips to Recycle at 2.75x metal prices (stated ~3x). Robustness share on the clean packs: 0.37 / 0.36 of 420 grid scenarios.
- Region tariff: `second_life.regions` with `global_default` (= today's PLACEHOLDER 0.08, decisions unchanged), `us_residential_avoided_purchase` 0.182 USD/kWh SOURCED (EIA STEO 2026 forecast ~18.2 c/kWh, https://www.eia.gov/outlooks/steo/report/elec_coal_renew.php, retrieved 2026-11-05 via a web-search summary; marked "verify on the page"), `india_wholesale_dam` kept PLACEHOLDER (IEX Aug 2026 DAM average INR 4.88/kWh noted with its URL, but the INR->USD rate and the arbitrage spread were not sourced).
- Reuse valuation: `low_speed_ev` now `valuation_mode: avoided_new_pack` (BNEF $108/kWh `new_ev_pack_usd_per_kwh`, status sourced, same URL; new assumed `new_ev_pack_life_years: 8` = typical EV warranty and the fleet registry's 8-year warranties). No buy-new storage cap for this mode.
- RESULT, reported honestly: still 0 REUSE on the fleet and on every reference bundle. Per kWh of usable capacity per year, reuse earns 108/8 = 13.5 USD while stationary storage is capped at 236/15 = 15.7 USD, and stationary use also lasts longer (SOH floor 60 % vs 65 %). Structural, so no DEMO-EXTRA packs were added (none could produce REUSE without changing numbers). The 23 reference decisions are all unchanged; only low_speed_ev net values moved (clean LFP -735 -> -1,178 USD, clean NMC -497 -> -1,749 USD).
- P2.10: NASA cell data not downloaded (time box), nothing retrained. The OOD/chemistry warning is a `warn` reason (impact 65) and halves the confidence in-distribution factor for NMC/NCA. "Known limits" section added to `docs/model_cards/state_rul.md`.
- Bugs found by running the fleet, fixed in Python and JS: a missing RUL bound and a never-reached application limit (central = None) crashed the Python explain on 3 packs; JS printed "0.0". Both now say "not reached within the projection horizon"; regression test added.
- Contracts: `assessment_report.schema.json` v1.1 (optional `insight`), new `battery_passport.schema.json`, CHANGELOG v1.1. ML API: `/assess?insight=true`, `/whatif`, `/passport`.
- Web port `engines/insight.js` (explain, confidence, reroute, breakEven, robustness, nextActions, ruleGap, impact, assign, passport). Goldens: `insight_cases.json` from Python (23 cases + a fleet-assignment case); `tests/insight.test.mjs`. `export_assets.py` now also exports `intelligence.yaml` and `battery_profiles.yaml` into `configs.json`.
- Fleet plan: greedy + 2-opt in both languages (same plan in parity test); Python also reports the exact scipy optimum for pack-count limits as a check.
- Tests: ML 117 passed; web 68/68 (23 insight parity + break-even + assign); API + DB 34 passed; `just check` 0 errors. Fleet parity Python/JS 70/70.

## P7 New frontend

- Done before P5/P6 per the priority order. New: `assets/css/pro.css` (dark navy default, light kept via data-theme), `pages/command.js`, `pack.js`, `live.js`, `history.js`, `ui/tour.js`, `ui/donut.js`, `ui/funnel.js`, `lib/fleet.js`, `workers/fleet.worker.js`, `tools/make_fleet_reports.mjs` (in `just web-regen`), `tests/fleet.test.mjs`.
- Decision: the app shell no longer blocks on the database. Engine assets load first, the fleet tables (~71k dense rows) load in the background, and only pages that need them wait (`needsDemo`). Command Center, Live and History render without them.
- Measured: the Command Center fleet table rendered 273 ms after navigation (warm cache, local server, `performance.mark("fleet-rendered")`).
- Fleet source order: live `/api/fleet` (when the API answers), then `data/fleet_reports.json` (snapshot), then a Web Worker computation cached in localStorage per `db_meta.generated_utc`.
- Verified in the built-in browser: Command Center (KPIs, donut, funnel, engine status strip, 70-pack table with URL-synced filters and paging, fleet plan); pack page (verdict, confidence factors, rule gap, reasons, projection bands, RUL bar, economics, what-if: DEMO-2W-PACK-017 flips to Recycle with the tariff below its 0.060 USD/kWh break-even); Live (stages light up from the real report, grey with reasons; Python parity badge "match" on clean_nmc); History (snapshot); guided demo bar starts from `#/command?demo=1`. Every old route still loads.
- Console: the only errors are `ERR_CONNECTION_REFUSED` from the Live-API probe when the API is stopped (a browser always logs a refused fetch). No script errors.
- Bench: `#/bench?preset=<fault>` starts the simulated ESP32 and injects that fault after 3 s; an alert timeline lists the firmware fault messages the BMS engine classified (the P3 alert engine itself was not built; see P3).
- Playwright is not installed, so there is no `tools/smoke.mjs` screenshot run; the click-through used the built-in browser instead.
- Tests: web 73/73 (new fleet.test.mjs: 5 tests).

## P5 Firmware, circuit, Wokwi, realistic circuit view

- Sketch v1.1.0 (A1-A6, E1-E3): 10x oversampling with software averaging (the Adafruit library has no public averaging API), RANGE_PROFILE (32V_2A default, 16V_400MA with its own 16 V / 0.4 A limits and messages), 80 MHz, Wi-Fi/BT off, yielding `delay(2)`, opt-in LOW_POWER_SLEEP (off; off under WOKWI), task watchdog guarded for core 2.x/3.x, `Wire.setTimeOut`, I2C bus-clear, `# boot reason=`, `# fw=` and `# ds18b20[i]=` boot lines, `# hb seq=` every 10 s, `seq`/`t_ms`/`ambient`/`crc` fields, repeated-warning throttling with `(x<n>)`. All existing `#` message texts unchanged.
- Decision (monitor-only vs bus-clear): A3 asks for an I2C bus-clear, E3 bans driving pins. Resolved by allowing ONLY `PIN_I2C_SCL` as OUTPUT_OPEN_DRAIN during the bus-clear (the I2C peripheral drives that line anyway); the guard allow-lists exactly that pin (and a future STATUS_LED_PIN). Nothing on the battery or load path is ever driven; no Serial.read.
- COMPILED (verified here): `arduino-cli` 1.5.1, esp32:esp32 core 3.3.12, both profiles (923,180 / 923,304 bytes, 70 % flash; 47,756 bytes RAM). arduino-cli exits non-zero AFTER producing the .bin/.elf because a PowerShell post-build hook of the core breaks on the apostrophe in the user folder; `scripts/fw_build.py` builds from a temp copy and checks the .bin/.elf exist. NOT flashed, NOT run on hardware.
- CRC: the prompt's example line has the real CRC `8C`. 7 vectors written by Python to `tests/golden/crc_vectors.json`; the JS port matches. Standard CRC-8 check value for "123456789" = 0xF4 verified.
- Consumers updated in one change: `contracts/esp32_line.schema.json` v1.1 (+CHANGELOG), `bms_engine` (CRC check -> `crc_errors`, seq gaps -> `dropped_lines`, `ambient` -> `Sample.ambient_temperature_c`, info prefixes, `(x<n>)` keeps base severity, fault_counts keyed by base text), `esp32_sim` (same fields, boot/heartbeat lines, throttling, faults `crc_corruption` and `seq_gap`), the JS ports `bms.js`/`esp32sim.js`, `runController.js` run rows, `test_run_log` columns `seq, t_ms, ambient_c, crc_ok` (ALTER ... ADD COLUMN IF NOT EXISTS; t_ms is not carried by Sample and stays NULL), the lite bridge passes `ambient` through as `ambient_temperature_c` (never invented).
- Circuit (P5.B): `engines/firmware/CIRCUIT.md` (wiring, fuse rule, power-resistor worked example, BOM with generic values, what-changed table). New parts in circuit.json: fuse, manual SPST switch, C1/C2 100 nF, C3 10 uF (conditional), I2C pull-ups (conditional), ambient DS18B20; all original pin ids kept. The direct battery->INA219 wire is replaced by battery->fuse->INA219, and INA219->load by INA219->switch->load (required by the fuse rule).
- Wokwi (P5.C, docs read via web fetch, 14 pages): confirmed `wokwi-ds18b20` (VCC/DQ/GND; deviceID; shared bus OK), `wokwi-resistor` (1/2, value), `board-esp32-devkit-c-v4`, diagram/connection format, wokwi.toml keys, Chips API (`*.chip.json`, `i2c_init`, `attr_init_float`), CLI flags and scenario format. No INA219 part -> custom chip sources `chips/ina219.chip.{json,c}`, NOT BUILT (no wasm toolchain). TODO verify: ESP32 board pin names (no docs page; 404), chip `controls` fields, iframe embedding (no docs found -> no iframe; open-link + zip download only).
- `diagram.json` is the single source of truth: `tools/wokwi_to_circuit.mjs` + `circuit_meta.json` write circuit.json; `just wokwi-sync` copies the sketch with `#define WOKWI 1` and checks both directions (0 problems). `export_assets.py` no longer rebuilds circuit.json from the Dash constants. Not done: the Dash Circuit Studio still draws from its own constants (time).
- E4 `scripts/check_circuit.py` and E3 `check_monitor_only.py` run in `just check` (0 failures). E5: no wokwi-cli here -> `last_run.json` = {ran:false, reason}; six scenarios written in the documented format (two need a part removed from the diagram, marked TODO verify).
- P5.D `ui/circuitView.js`: part graphics per kind with fallback, colour-coded right-angle wires with rounded corners and junction dots, live flow/tags/LED/link stats/alert pulses only from a real snapshot, pin tooltips, net highlight, keyboard focus, reduced motion, SVG/PNG download. Verified in the browser (hardware page static, bench live with the over-voltage preset). OneDrive briefly locked circuit.json twice during writes; the generator now retries.
- Tests (P5): engines/bms/test_firmware_lines.py 8 passed + 1 skipped (no Wokwi capture); web 80/80 (new firmware.test.mjs, circuit.test.mjs; the simulator-sequence test now counts each boot line as one readline call, as the Python harness does).

## P6 API service

- New `routes_fleet.py` + `services/fleet.py`, mounted from `main.py` (2 lines): `/api/fleet` (paging, search, filters, sort), `/api/fleet/summary`, `/api/fleet/plan`, `/api/fleet/refresh` (single writer), `/api/battery/{id}`, `/history`, `/passport`, `/api/whatif`, `/api/meta`, `/api/history/assessments|suggestions|runs`.
- Decision: fleet records use the same compact shape as the web app's `lib/fleet.js`, so the Command Center prefers `/api/fleet` when the API answers and falls back to the snapshot otherwise.
- Bug found by the tests: fetching a TIMESTAMPTZ scalar needs `pytz` (not installed by design); the meta query casts to text.
- `registry.json`: firmware, bms, database, ml, api, web-studio and platform-config "run after change" lists updated; `just impact engines/ml/configs/limits.yaml` lists the web-studio regeneration steps including `make_fleet_reports.mjs`.
- Tests: API 31 passed (new test_fleet_api.py: 6 tests, including the tariff flip through /api/whatif and a full refresh with 0 errors).

## P9 Final verification

- `just web-db` (rebuild + fleet + web copy) and `just web-regen` from scratch; all suites rerun (counts in the final report above).
- Fleet counts identical in Python and JS (scripts/fleet_parity.py 70/70); 23-bundle parity green in `npm test`.
- Browser, API stopped (P7) and running (P9): every route loads; the Command Center source is "snapshot" or "live API" accordingly; no external requests; no console errors with the API running.
- No hard-coded absolute paths in the web app; the only external URL is the opt-in DuckDB-WASM CDN. Every pack is labelled SYNTHETIC; placeholder inputs are listed on every report.
- Files under `apps/web-studio/data/` and `tests/golden/` were written only by the tools (`export_assets.py`, `make_golden.py`, `make_bundles.mjs`, `make_fleet_reports.mjs`, `wokwi_to_circuit.mjs`, `refresh_web_copy.py`).
- Firmware: `just wokwi-sync` 0 problems; `just fw-build` compiled both profiles; CRC vectors match in Python and JS; old v1.0 lines parse; no `Serial.read`; the only driven pin is SCL during the bus-clear (allow-listed); no request to Wokwi at page load.
