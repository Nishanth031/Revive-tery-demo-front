"""`just wokwi-sync`: (1) copy the firmware to engines/firmware/wokwi/sketch.ino with WOKWI set, (2) regenerate
apps/web-studio/data/circuit.json from diagram.json + circuit_meta.json, (3) check that they agree.

Checks: the sketch copy equals the firmware (ignoring the WOKWI define); every wire pin exists in a component;
every diagram.json connection appears in circuit.json and the other way round (for parts Wokwi simulates).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FW = ROOT / "engines" / "firmware" / "revive_tery_esp32" / "revive_tery_esp32.ino"
WOKWI = ROOT / "engines" / "firmware" / "wokwi"
WEB = ROOT / "apps" / "web-studio"
DEFINE = "#define WOKWI 1   // set here only: the Wokwi copy of the firmware (just wokwi-sync)\n"


def sync_sketch() -> None:
    (WOKWI / "sketch.ino").write_text(DEFINE + FW.read_text(encoding="utf-8"), encoding="utf-8")


def problems() -> list[str]:
    errs = []
    copy = (WOKWI / "sketch.ino").read_text(encoding="utf-8")
    if copy.replace(DEFINE, "", 1) != FW.read_text(encoding="utf-8"):
        errs.append("wokwi/sketch.ino differs from the firmware (run just wokwi-sync)")
    circuit = json.loads((WEB / "data" / "circuit.json").read_text(encoding="utf-8"))
    pins = {p["id"] for c in circuit["components"] for p in c["pins"]}
    for w in circuit["wires"]:
        for end in (w["from"], w["to"]):
            if end not in pins:
                errs.append(f"wire {w['from']} -> {w['to']}: pin {end} is in no component")
    diagram = json.loads((WOKWI / "diagram.json").read_text(encoding="utf-8"))
    d = {tuple(sorted(c[:2])) for c in diagram["connections"] if not c[0].startswith("$") and not c[1].startswith("$")}
    c = {tuple(sorted(w["wokwi"])) for w in circuit["wires"] if w.get("wokwi")}
    errs += [f"diagram connection {x} missing from circuit.json" for x in sorted(d - c)]
    errs += [f"circuit.json wire {x} is not in diagram.json" for x in sorted(c - d)]
    return errs


def main() -> int:
    sync_sketch()
    subprocess.run(["node", "tools/wokwi_to_circuit.mjs"], cwd=WEB, check=True)
    errs = problems()
    for e in errs:
        print("WOKWI SYNC:", e)
    print(f"wokwi-sync: {len(errs)} problem(s)")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
