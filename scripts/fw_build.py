"""`just fw-build`: compile the sketch for esp32:esp32:esp32 with arduino-cli, both range profiles, and put the
default profile's .bin/.elf where engines/firmware/wokwi/wokwi.toml expects them (build/sketch.ino.bin/.elf).

Needs arduino-cli with the esp32:esp32 core and the libraries Adafruit INA219, OneWire, DallasTemperature
(`--install` installs them). The sketch is copied to a temp folder first: on this machine the user folder name contains
an apostrophe, which breaks a PowerShell post-build hook of the ESP32 core; a compile counts as successful when the
.bin and .elf were produced. Compiling is not flashing: nothing here touches hardware.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKETCH = ROOT / "engines" / "firmware" / "revive_tery_esp32" / "revive_tery_esp32.ino"
OUT = ROOT / "engines" / "firmware" / "wokwi" / "build"
FQBN = "esp32:esp32:esp32"
PROFILES = {"RANGE_32V_2A": 1, "RANGE_16V_400MA": 2}


def main() -> int:
    cli = shutil.which("arduino-cli") or r"C:\Program Files\Arduino CLI\arduino-cli.exe"
    if not Path(cli).exists() and not shutil.which("arduino-cli"):
        print("fw-build: arduino-cli not found; the sketch was NOT compiled")
        return 0
    if "--install" in sys.argv:
        subprocess.run([cli, "core", "install", "esp32:esp32"], check=False)
        subprocess.run([cli, "lib", "install", "Adafruit INA219", "OneWire", "DallasTemperature"], check=False)
    tmp = Path(tempfile.mkdtemp(prefix="revive_fw_"))
    ok_all = True
    try:
        src = tmp / "revive_tery_esp32"
        src.mkdir()
        shutil.copy2(SKETCH, src / SKETCH.name)
        for name, val in PROFILES.items():
            build = tmp / f"build_{name}"
            r = subprocess.run([cli, "compile", "--fqbn", FQBN, "--build-path", str(build),
                                "--build-property", f"compiler.cpp.extra_flags=-DRANGE_PROFILE={val}", str(src)],
                               capture_output=True, text=True)
            usage = [l for l in r.stdout.splitlines() if l.startswith(("Sketch uses", "Global variables"))]
            binf, elf = build / f"{SKETCH.name}.bin", build / f"{SKETCH.name}.elf"
            ok = binf.is_file() and elf.is_file() and any(l.startswith("Sketch uses") for l in usage)
            ok_all &= ok
            print(f"{name}: {'COMPILED' if ok else 'FAILED'}  " + " | ".join(usage))
            if not ok:
                print(r.stdout[-2000:], r.stderr[-2000:])
            if ok and r.returncode != 0:
                print("  note: arduino-cli exited non-zero after producing the .bin/.elf (a post-build hook); treated as compiled")
            if ok and name == "RANGE_32V_2A":
                OUT.mkdir(parents=True, exist_ok=True)
                shutil.copy2(binf, OUT / "sketch.ino.bin")
                shutil.copy2(elf, OUT / "sketch.ino.elf")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
