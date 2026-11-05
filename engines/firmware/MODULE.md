# engines/firmware: ESP32 telemetry firmware

**Purpose:** read pack voltage/current (INA219) and temperature (DS18B20), print one JSON line per second at 115200 baud.
**Public interface (do not break):** the line format in `contracts/esp32_line.schema.json`; `#` lines are messages.
**Safety:** monitor-only (never reads serial, drives no outputs). Bench use only, INA219 max 26 V, never an EV pack.
**Origin:** `bulid X/firmware/revive_tery_esp32/`.
**Edit rules:** if you change the JSON keys or the `#` messages, update `contracts/esp32_line.schema.json`, `engines/bms/bms_engine.py` (`parse_telemetry_line`, `firmware_message_severity`) and `apps/web-studio/assets/js/engines/bms.js`, then `just impact`.
**Test:** flash with Arduino IDE (esp32 core; libs Adafruit INA219, OneWire, DallasTemperature) and watch the serial monitor.

**v1.1.0 (upgrade P5):** oversampled averages, `RANGE_PROFILE` (32V_2A default, 16V_400MA), 80 MHz + radios off, watchdog, I2C timeout + bus-clear (the only driven pin: SCL, open-drain), optional `ambient`/`seq`/`t_ms`/`crc`, boot/version/heartbeat lines, throttled repeats `(x<n>)`. Contract: `contracts/esp32_line.schema.json` v1.1. Circuit: `CIRCUIT.md`. Wokwi: `wokwi/` (diagram.json is the single source of truth for the web circuit). Commands: `just fw-build` (compiled with arduino-cli + esp32 core 3.3.12; never flashed here), `just wokwi-sync`, `just wokwi-check`, `just check` (monitor-only guard + circuit rules).
