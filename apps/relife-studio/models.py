"""Shared types for ReLife BMS. Simulation only; no hardware I/O."""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field, fields
from typing import Any

UNKNOWN_TEXT = ("", "Unknown", "unknown")

_INT_FIELDS = ("series_cells", "parallel_cells", "cycle_count")
_FLOAT_FIELDS = (
    "nominal_voltage_v", "capacity_value", "rated_energy_wh", "charge_limit_a", "discharge_limit_a",
    "mass_kg", "measured_capacity_ah", "measured_voltage_v", "measured_current_a",
    "measured_temperature_c", "soh_pct", "initial_soc_pct", "internal_resistance_mohm",
)
_FIELD_NAMES = None


def _parse_number(value: Any, integer: bool = False) -> int | float | None:
    """Convert a value to a number, or None when it is blank or not a real number."""
    if value is None or value in UNKNOWN_TEXT:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return int(number) if integer else number


@dataclass
class BatteryProfile:
    id: str
    name: str
    chemistry: str = "Unknown"
    manufacturer: str = "Unknown"
    model: str = "Unknown"
    category: str = "Unclassified"
    series_cells: int | None = None
    parallel_cells: int | None = None
    nominal_voltage_v: float | None = None
    capacity_value: float | None = None
    capacity_unit: str = "Ah"
    rated_energy_wh: float | None = None
    charge_limit_a: float | None = None
    discharge_limit_a: float | None = None
    mass_kg: float | None = None
    manufacture_date: str = "Unknown"
    condition: str = "Unknown"
    cycle_count: int | None = None
    measured_capacity_ah: float | None = None
    measured_voltage_v: float | None = None
    measured_current_a: float | None = None
    measured_temperature_c: float | None = None
    soh_pct: float | None = None
    initial_soc_pct: float | None = None
    internal_resistance_mohm: float | None = None
    source_kind: str = "user_entered"
    source_title: str = "User entry"
    source_url: str = ""
    license: str = "User-provided"
    measurement_method: str = "Not specified"
    notes: str = ""
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "BatteryProfile":
        """Build a profile from JSON or a CSV row. Bad numbers become unknown, not errors."""
        global _FIELD_NAMES
        if _FIELD_NAMES is None:
            _FIELD_NAMES = {f.name for f in fields(cls)}
        clean = {key: value for key, value in data.items() if key in _FIELD_NAMES}
        for key in _INT_FIELDS:
            clean[key] = _parse_number(clean.get(key), integer=True)
        for key in _FLOAT_FIELDS:
            clean[key] = _parse_number(clean.get(key))

        clean["id"] = str(clean.get("id") or "").strip()
        clean["name"] = str(clean.get("name") or "").strip() or clean["id"]
        # A blank CSV cell must fall back to the field's default, not overwrite it.
        for f in fields(cls):
            if f.type == "str" and f.name not in ("id", "name") and clean.get(f.name) in (None, ""):
                clean.pop(f.name, None)
        tags = clean.get("tags")
        if isinstance(tags, str):
            clean["tags"] = [tag.strip() for tag in tags.split(",") if tag.strip()]
        elif tags is None:
            clean.pop("tags", None)
        return cls(**clean)

    def completeness(self) -> tuple[str, list[str]]:
        missing = []
        for key, label in (
            ("chemistry", "chemistry"),
            ("series_cells", "series cell count"),
            ("nominal_voltage_v", "nominal voltage"),
            ("capacity_value", "rated capacity"),
            ("charge_limit_a", "charge current limit"),
            ("discharge_limit_a", "discharge current limit"),
        ):
            value = getattr(self, key)
            if value is None or (isinstance(value, str) and value in UNKNOWN_TEXT):
                missing.append(label)
        return ("READY FOR SIMULATION" if not missing else "INCOMPLETE PROFILE", missing)


@dataclass
class HardwareAdapter:
    id: str
    name: str
    chemistry_families: list[str]
    min_series: int
    max_series: int
    max_stack_voltage_v: float
    max_temperature_channels: int = 9
    balancing_supported: bool = True
    simulated_only: bool = True


@dataclass
class Measurement:
    name: str
    value: float | None
    unit: str
    source: str
    quality: str = "valid"
    timestamp: str = ""
