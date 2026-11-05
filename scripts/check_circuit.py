"""Circuit design-rule check on apps/web-studio/data/circuit.json (run by `just check`).

Rules: every wire references existing pins; a pin carries one net only unless the net is a declared shared one
(3V3, GND, SDA, SCL, 1-Wire); battery positive reaches the INA219 VIN+ only through the fuse; the INA219 is the only
sensor on the battery path; no ESP32 GPIO is on a power or ground wire; the configured bus voltage limit is <= 26 V;
every component kind has a renderer (or the fallback box).
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CIRCUIT = ROOT / "apps" / "web-studio" / "data" / "circuit.json"
KNOWN_KINDS = {"battery", "load", "sensor", "passive", "mcu", "host", "fuse", "switch", "capacitor"}
SHARED_NETS = {"logic", "ground", "i2c", "i2c_scl", "onewire"}
POWER_TYPES = {"power", "ground"}
INA219_LIMIT_V = 26.0


def nets(circuit):
    """Union-find over wires: pin -> net representative."""
    parent = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for w in circuit["wires"]:
        parent[find(w["from"])] = find(w["to"])
    return find


def check(circuit) -> list[str]:
    fails = []
    pins = {p["id"]: c for c in circuit["components"] for p in c["pins"]}
    for w in circuit["wires"]:
        for end in (w["from"], w["to"]):
            if end not in pins:
                fails.append(f"wire {w['from']} -> {w['to']}: unknown pin {end}")
    types_at = defaultdict(set)
    for w in circuit["wires"]:
        for end in (w["from"], w["to"]):
            types_at[end].add(w["type"])
    for pin, types in types_at.items():
        if len(types) > 1 and not types <= SHARED_NETS:
            fails.append(f"pin {pin} joins different nets: {sorted(types)}")
    # battery + to INA219 VIN+ only through the fuse: no direct wire, and the fuse sits between them
    direct = [w for w in circuit["wires"] if {w["from"], w["to"]} == {"bat_pos", "ina_vin_pos"}]
    if direct:
        fails.append("battery + is wired straight to INA219 VIN+ (the fuse must be in between)")
    adj = defaultdict(set)
    for w in circuit["wires"]:
        if w["type"] == "power":
            adj[w["from"]].add(w["to"])
            adj[w["to"]].add(w["from"])
    comp_of = {p: c["id"] for p, c in pins.items()}
    # walk from bat_pos without passing through the fuse component: INA219 VIN+ must be unreachable
    seen, stack = {"bat_pos"}, ["bat_pos"]
    while stack:
        x = stack.pop()
        for y in adj[x]:
            if y in seen or comp_of.get(y) == "fuse":
                continue
            seen.add(y)
            stack.append(y)
    if "ina_vin_pos" in seen:
        fails.append("a path from battery + reaches INA219 VIN+ without the fuse")
    sensors_on_path = {comp_of[p] for p in adj if pins[p]["kind"] == "sensor"}
    if sensors_on_path - {"ina219"}:
        fails.append(f"other sensors on the battery path: {sorted(sensors_on_path - {'ina219'})}")
    for w in circuit["wires"]:
        if w["type"] in POWER_TYPES:
            for end in (w["from"], w["to"]):
                if end.startswith("esp_") and end not in ("esp_gnd",) and w["type"] == "power":
                    fails.append(f"ESP32 pin {end} is on a power wire")
                if end in ("esp_21", "esp_22", "esp_4"):
                    fails.append(f"ESP32 GPIO {end} is on a {w['type']} wire")
    if float(circuit.get("max_bus_voltage_v", INA219_LIMIT_V)) > INA219_LIMIT_V:
        fails.append(f"max_bus_voltage_v {circuit['max_bus_voltage_v']} exceeds the INA219's 26 V")
    for c in circuit["components"]:
        if c["kind"] not in KNOWN_KINDS:
            fails.append(f"component {c['id']}: kind {c['kind']!r} has no renderer (the fallback box will be used)")
    return fails


def main() -> int:
    fails = check(json.loads(CIRCUIT.read_text(encoding="utf-8")))
    if fails:
        print(f"{'rule':<6}| failure")
        for f in fails:
            print(f"{'FAIL':<6}| {f}")
    print(f"circuit check: {len(fails)} failure(s)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
