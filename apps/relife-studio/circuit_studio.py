"""Editable conceptual schematic model and component catalog."""
from __future__ import annotations

from dataclasses import dataclass, field

COMPONENTS = {
    "BAT1": ("Battery cell stack", "battery", "PACK+ / PACK− / CELL_TAP[n]"),
    "F1": ("Pack fuse", "fuse", "PACK+"),
    "U1": ("Cell monitor AFE", "afe", "CELL_TAP[n] / THERM[n] / AFE_LINK"),
    "RSH1": ("Current shunt / sensor", "shunt", "PACK_CURRENT / SENSE_P / SENSE_N"),
    "TH1": ("NTC temperature sensor", "thermistor", "THERM[n]"),
    "RB1": ("Balance resistor + switch", "balance", "CELL[n] / AFE_CTRL"),
    "U2": ("BMS controller MCU", "mcu", "AFE_LINK / CTRL_* / CAN_*"),
    "Q1": ("Charge/discharge switches", "switch", "PACK+ / CTRL_*"),
    "DRV1": ("Protected driver interface", "driver", "CTRL_* / SWITCH_GATE"),
    "ISO1": ("Isolated communications", "isolation", "MCU_LINK / ISOLATED_BUS"),
    "J1": ("Pack output connector", "connector", "PACK+ / PACK−"),
    "KPRE": ("Optional precharge function", "precharge", "PACK+ / DC_LINK"),
    "VM1": ("Pack voltage monitor", "voltmeter", "PACK+ / PACK− / ADC"),
    "PS1": ("Isolated DC/DC auxiliary supply", "supply", "PACK / ISOLATED_LOGIC"),
}
PART_KINDS = sorted({kind for _, kind, _ in COMPONENTS.values()})


@dataclass
class Part:
    ref: str
    name: str
    kind: str
    x: float
    y: float
    pins: list[str]


@dataclass
class Net:
    name: str
    net_type: str
    endpoints: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class CircuitDesign:
    parts: list[Part] = field(default_factory=list)
    nets: list[Net] = field(default_factory=list)

    @classmethod
    def starter(cls) -> "CircuitDesign":
        parts = [
            Part("BAT1", "Virtual battery cell stack", "battery", 40, 130, ["PACK+", "PACK−", "CELL_TAP[n]"]),
            Part("F1", "Pack fuse", "fuse", 230, 130, ["IN", "OUT"]),
            Part("Q1", "Charge/discharge switches", "switch", 420, 130, ["PACK_IN", "PACK_OUT", "CTRL"]),
            Part("J1", "Pack output connector", "connector", 610, 130, ["PACK+", "PACK−"]),
            Part("RSH1", "Current shunt / sensor", "shunt", 420, 270, ["SENSE_P", "SENSE_N"]),
            Part("U1", "Cell monitor AFE", "afe", 230, 390, ["CELL_TAP[n]", "THERM[n]", "AFE_LINK"]),
            Part("U2", "BMS controller MCU", "mcu", 440, 440, ["AFE_LINK", "CTRL_*", "CAN_*"]),
            Part("TH1", "NTC temperature sensors", "thermistor", 40, 390, ["THERM[n]"]),
            Part("RB1", "Balance resistor + switch bank", "balance", 40, 500, ["CELL[n]", "AFE_CTRL"]),
            Part("DRV1", "Protected switch driver", "driver", 650, 420, ["CTRL_*", "SWITCH_GATE"]),
            Part("ISO1", "Isolated communications", "isolation", 850, 420, ["MCU_LINK", "ISOLATED_BUS"]),
            Part("KPRE", "Optional precharge function", "precharge", 610, 270, ["PACK+", "DC_LINK"]),
            Part("VM1", "Pack voltage monitor / divider", "voltmeter", 820, 130, ["PACK+", "PACK−", "ADC"]),
            Part("PS1", "Isolated DC/DC auxiliary supply", "supply", 850, 540, ["PACK", "ISOLATED_LOGIC"]),
        ]
        nets = [
            Net("PACK+", "power", [("BAT1", "PACK+"), ("F1", "IN")]),
            Net("FUSED+", "power", [("F1", "OUT"), ("Q1", "PACK_IN")]),
            Net("OUTPUT+", "power", [("Q1", "PACK_OUT"), ("J1", "PACK+")]),
            Net("CELL_TAP[n]", "sense", [("BAT1", "CELL_TAP[n]"), ("U1", "CELL_TAP[n]")]),
            Net("THERM[n]", "sense", [("TH1", "THERM[n]"), ("U1", "THERM[n]")]),
            Net("AFE_LINK", "signal", [("U1", "AFE_LINK"), ("U2", "AFE_LINK")]),
            Net("SENSE_P", "sense", [("RSH1", "SENSE_P"), ("U1", "SENSE_P")]),
            Net("SENSE_N", "sense", [("RSH1", "SENSE_N"), ("U1", "SENSE_N")]),
            Net("CTRL", "control", [("U2", "CTRL_*"), ("DRV1", "CTRL_*")]),
            Net("SW_GATE", "control", [("DRV1", "SWITCH_GATE"), ("Q1", "CTRL")]),
            Net("CAN", "isolated", [("U2", "CAN_*"), ("ISO1", "MCU_LINK")]),
            Net("BALANCE", "control", [("U1", "AFE_CTRL"), ("RB1", "AFE_CTRL")]),
        ]
        return cls(parts, nets)

    def add_part(self, ref: str, name: str, kind: str, x: float, y: float, pins: list[str]) -> Part:
        if any(p.ref == ref for p in self.parts):
            raise ValueError("Reference already exists")
        part = Part(ref, name, kind, x, y, pins)
        self.parts.append(part)
        return part

    def move(self, ref: str, x: float, y: float) -> None:
        part = next((p for p in self.parts if p.ref == ref), None)
        if not part:
            raise ValueError("Unknown part")
        part.x = x
        part.y = y

    def nets_for(self, ref: str) -> list[Net]:
        return [net for net in self.nets if any(end_ref == ref for end_ref, _ in net.endpoints)]

    def next_ref(self) -> str:
        existing = {p.ref for p in self.parts}
        n = len(self.parts) + 1
        while f"X{n}" in existing:
            n += 1
        return f"X{n}"
