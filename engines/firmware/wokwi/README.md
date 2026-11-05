# REVIVE-TERY bench in Wokwi

Files: `diagram.json` (connections: the single source of truth for the web circuit), `circuit_meta.json` (titles,
layout, parts Wokwi cannot simulate), `sketch.ino` (copy of the firmware with `#define WOKWI 1`, kept in sync by
`just wokwi-sync`), `libraries.txt`, `wokwi.toml`, `chips/ina219.chip.json` + `chips/ina219.chip.c` (INA219 custom
chip), `scenarios/*.yaml`, `capture_serial.md`.

## Status (2026-11-05)

- Part types confirmed from docs.wokwi.com: `wokwi-ds18b20` (pins VCC, DQ, GND; attrs `temperature`, `deviceID`; several
  sensors may share one data pin with unique `deviceID`s), `wokwi-resistor` (pins 1, 2; attr `value`),
  `board-esp32-devkit-c-v4` (listed in the diagram-format page). There is no INA219 part, so a custom chip is used.
- **TODO verify:** the ESP32 board pin names (`3V3`, `GND.1`, `21`, `22`, `4`, `TX`, `RX`): the board has no docs page.
  Hover the pins in the Wokwi editor or run `wokwi-cli lint`, and fix `diagram.json` + `circuit_meta.json` if needed.
- **TODO verify:** the `controls` fields in `ina219.chip.json` (the chip-json page documents `controls` but not its fields).
- **Custom chip NOT built here.** Build `chips/ina219.chip.wasm` with the Wokwi chip toolchain (Chips API, beta), or
  create a custom chip in the online editor and paste `ina219.chip.c` / `ina219.chip.json`.
- Firmware: `just fw-build` compiled both range profiles with arduino-cli and esp32 core 3.3.12 and copied
  `build/sketch.ino.bin/.elf`. Nothing was flashed or run on hardware.
- No wokwi-cli in this environment: no lint, scenario or capture has run (`last_run.json` says so).

## Run it on wokwi.com

1. New project -> ESP32. Replace `diagram.json` and `sketch.ino` with these files, add `libraries.txt`.
2. Add the custom chip `ina219` (files in `chips/`). Start the simulation; the INA219 sliders set bus voltage and current.
3. Share: Save, then copy the project URL into `config/platform.json` -> `wokwi.project_url`; the web app's
   "Simulate in Wokwi" button opens it (no request to Wokwi is made until you click).

## CLI (VS Code extension or wokwi-cli)

`wokwi.toml` points at `build/sketch.ino.bin` / `.elf` (from `just fw-build`). With wokwi-cli installed:

    wokwi-cli lint .
    wokwi-cli . --timeout 60000 --serial-log-file captured_serial.log
    wokwi-cli . --scenario scenarios/03_over_voltage.yaml

The token is read from the `WOKWI_CLI_TOKEN` environment variable (created on the Wokwi CI dashboard). Never store it in
the repo. `just wokwi-check` runs all of this when the CLI and the token exist and writes `last_run.json`; otherwise it
writes `{ran:false, reason}` and the build stays green.
