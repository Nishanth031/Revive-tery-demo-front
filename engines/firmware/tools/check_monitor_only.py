"""Monitor-only guard for the ESP32 sketch (run by `just check`).

Fails (exit 1) when a sketch or header reads from the serial port or drives an output pin:
Serial.read / Serial.available / Serial.readString / readBytes, digitalWrite, analogWrite, ledcWrite, dacWrite,
pinMode(..., OUTPUT).

Allow-list (documented in the sketch): the I2C clock line PIN_I2C_SCL may be driven open-drain during an I2C
bus-clear (what the I2C peripheral itself does on that line); and a status-LED pin named STATUS_LED_PIN, if one is
ever added. Nothing on the battery or load path can be driven.

    python engines/firmware/tools/check_monitor_only.py [files...]   (default: every .ino/.h under engines/firmware)
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALLOWED_PINS = ("PIN_I2C_SCL", "STATUS_LED_PIN")
RULES = [
    (re.compile(r"\bSerial\d?\s*\.\s*(read|available|readString|readStringUntil|readBytes|readBytesUntil|peek|parseInt|parseFloat)\s*\("), "reads from the serial port"),
    (re.compile(r"(?<![\w.])readBytes\s*\("), "reads bytes from a stream"),
    (re.compile(r"\banalogWrite\s*\("), "drives an analog output"),
    (re.compile(r"\bledcWrite\s*\("), "drives a PWM output"),
    (re.compile(r"\bdacWrite\s*\("), "drives the DAC"),
]
DIGITAL_WRITE = re.compile(r"\bdigitalWrite\s*\(\s*([A-Za-z_]\w*|\d+)")
PIN_MODE = re.compile(r"\bpinMode\s*\(\s*([A-Za-z_]\w*|\d+)\s*,\s*(OUTPUT(?:_OPEN_DRAIN)?)\s*\)")


def strip_comments(src: str) -> str:
    src = re.sub(r"/\*.*?\*/", lambda m: "\n" * m.group(0).count("\n"), src, flags=re.S)
    return re.sub(r"//[^\n]*", "", src)


def check(path: Path) -> list[str]:
    errs = []
    for no, line in enumerate(strip_comments(path.read_text(encoding="utf-8", errors="replace")).splitlines(), 1):
        for rx, why in RULES:
            if rx.search(line):
                errs.append(f"{path.name}:{no}: {why}: {line.strip()}")
        for m in DIGITAL_WRITE.finditer(line):
            if m.group(1) not in ALLOWED_PINS:
                errs.append(f"{path.name}:{no}: drives pin {m.group(1)} (digitalWrite): {line.strip()}")
        for m in PIN_MODE.finditer(line):
            pin, mode = m.group(1), m.group(2)
            if not (pin == "PIN_I2C_SCL" and mode == "OUTPUT_OPEN_DRAIN") and pin != "STATUS_LED_PIN":
                errs.append(f"{path.name}:{no}: makes pin {pin} an {mode}: {line.strip()}")
    return errs


def main(argv: list[str]) -> int:
    files = [Path(a) for a in argv] or sorted([*ROOT.rglob("*.ino"), *ROOT.rglob("*.h")])
    errs = [e for f in files for e in check(f)]
    for e in errs:
        print("MONITOR-ONLY VIOLATION", e)
    print(f"monitor-only check: {len(files)} file(s), {len(errs)} violation(s)")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
