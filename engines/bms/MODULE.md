# engines/bms: BMS engine, ESP32 simulator, run controller

**Purpose:** turn samples (virtual replay / simulated ESP32 / real ESP32 over serial) into readings: voltage, current, temperature, SOC (coulomb counting), SOH with a stated basis, link statistics, tier decision.
**Files:** `bms_engine.py` (profiles from DuckDB, SOC/SOH, read-only serial, line parser, telemetry logger) · `esp32_sim.py` (software ESP32 + fault injection) · `run_controller.py` (threaded run orchestration, `snapshot()`) · `test_bench.py`.
**Public interface:** `BMSEngine`, `RunController` (`start_virtual/start_simulated/start_hardware/stop/snapshot`), `parse_telemetry_line`, `SimulatedESP32`, `load_battery_profile`, `DB_PATH`.
**Imports are flat** (`import bms_engine`). The platform adds `engines/bms` to `PYTHONPATH`; do not turn these into a package.
**Rules:** never write to the ESP32; never flip the current sign; no invented values.
**Origin:** `bulid X/src/`. (Not the same file as `apps/relife-studio/bms_engine.py`.)
**Test:** `just test-api` (exercises runs through the API). **Port:** `apps/web-studio/assets/js/engines/{bms,esp32sim,runController}.js` must match.

**Firmware v1.1 lines:** `line_crc_ok`, `crc8`; `Sample.ambient_temperature_c` and `Sample.seq`; `SerialStats.crc_errors`, `dropped_lines`, `note_seq`; info prefixes `# fw=`, `# hb`, `# boot`, `# ds18b20`; a `(x<n>)` repeat keeps its base severity. `esp32_sim` emits the same lines, with faults `crc_corruption` and `seq_gap`. `test_run_log` gains `seq, t_ms, ambient_c, crc_ok`. Tests: `test_firmware_lines.py` (`just test-bms`). The P3 alert engine and SOC recalibration were NOT built (see UPGRADE_LOG.md).
