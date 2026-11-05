# Capture 60 s of simulated serial output

Needs wokwi-cli and the `WOKWI_CLI_TOKEN` environment variable (never commit it), and a firmware build (`just fw-build`).

    python engines/firmware/wokwi/capture_serial.py

writes `captured_serial.log` here. `engines/bms/test_firmware_lines.py` then checks that at least 95 % of its telemetry
lines parse with `bms_engine.parse_telemetry_line`; without the file that test is skipped.
