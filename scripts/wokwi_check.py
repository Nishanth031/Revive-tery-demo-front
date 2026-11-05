"""`just wokwi-check`: lint and run the Wokwi project when the tools exist; never fails the build when they don't.

- `wokwi-cli lint` when wokwi-cli is installed;
- the scenarios and a 60 s serial capture only when wokwi-cli AND WOKWI_CLI_TOKEN exist;
- the captured log parsed with bms_engine.parse_telemetry_line (bad CRC and dropped lines counted).
Writes engines/firmware/wokwi/last_run.json: {ran_utc, lint_ok, scenarios:[{name, passed}], lines, bad_crc, dropped}
or {ran: false, reason}. The token comes from the environment only and is never written anywhere.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WOKWI = ROOT / "engines" / "firmware" / "wokwi"
OUT = WOKWI / "last_run.json"
sys.path.insert(0, str(ROOT / "engines" / "bms"))


def write(obj) -> int:
    OUT.write_text(json.dumps(obj, indent=1), encoding="utf-8")
    print(json.dumps(obj))
    return 0


def main() -> int:
    cli = shutil.which("wokwi-cli")
    if not cli:
        return write({"ran": False, "reason": "wokwi-cli is not installed here", "checked_utc": datetime.now(UTC).isoformat(timespec="seconds")})
    lint = subprocess.run([cli, "lint", str(WOKWI)], capture_output=True, text=True)
    if not os.environ.get("WOKWI_CLI_TOKEN"):
        return write({"ran": False, "lint_ok": lint.returncode == 0, "reason": "WOKWI_CLI_TOKEN is not set (scenarios and capture skipped)",
                      "checked_utc": datetime.now(UTC).isoformat(timespec="seconds")})
    if not (WOKWI / "build" / "sketch.ino.bin").is_file():
        return write({"ran": False, "lint_ok": lint.returncode == 0, "reason": "no firmware build (run just fw-build)"})
    results = []
    for sc in sorted((WOKWI / "scenarios").glob("*.yaml")):
        r = subprocess.run([cli, str(WOKWI), "--scenario", str(sc.relative_to(WOKWI)), "--timeout", "60000"], capture_output=True, text=True)
        results.append({"name": sc.stem, "passed": r.returncode == 0})
    log = WOKWI / "captured_serial.log"
    subprocess.run([cli, str(WOKWI), "--timeout", "60000", "--serial-log-file", str(log)], capture_output=True, text=True)
    import bms_engine as bms
    stats = bms.SerialStats()
    lines = log.read_text(encoding="utf-8", errors="replace").splitlines() if log.is_file() else []
    good = 0
    for line in lines:
        raw = line.encode()
        if not line.startswith("{"):
            continue
        if bms.line_crc_ok(raw) is False:
            stats.crc_errors += 1
            continue
        s = bms.parse_telemetry_line(raw, 0)
        if s:
            stats.note_seq(s.seq)
            good += 1
    return write({"ran_utc": datetime.now(UTC).isoformat(timespec="seconds"), "lint_ok": lint.returncode == 0,
                  "scenarios": results, "lines": good, "bad_crc": stats.crc_errors, "dropped": stats.dropped_lines})


if __name__ == "__main__":
    sys.exit(main())
