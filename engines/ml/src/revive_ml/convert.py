"""Convert the REVIVE-TERY demo CSV bundle into a contract bundle.

The column mapping is explicit and documented in PLAN.md. Values are copied, never altered:
current keeps its recorded sign, timestamps keep their recorded spacing.
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from revive_ml.contract import (
    CapacityTest,
    ContractError,
    Metadata,
    ResistanceTest,
    SafetyEvent,
    write_bundle,
)
from revive_ml.paths import REPO_ROOT

DEMO_SOURCE = REPO_ROOT / "examples" / "demo_source"

TELEMETRY_MAP = {
    "timestamp_utc": "timestamp_utc",
    "asset_id": "asset_id",
    "pack_voltage_V": "voltage_v",
    "pack_current_A": "current_a",
    "max_cell_temp_C": "temperature_c",  # hottest cell: conservative for safety limits
    "soc_pct": "soc_pct",
    "min_cell_temp_C": "min_temperature_c",
    "ambient_temp_C": "ambient_temperature_c",
    "power_kW": "power_kw",
    "operating_state": "operating_state",
    "soh_pct": "bms_soh_pct",
}
CHEMISTRY_MAP = {
    "NMC (nickel manganese cobalt)": "NMC",
    "NMC": "NMC",
    "LFP": "LFP",
    "LFP (lithium iron phosphate)": "LFP",
    "NCA": "NCA",
    "NCA (nickel cobalt aluminium)": "NCA",   # label used by the user's 60-pack fleet database
}
PROVENANCE_MAP = {"SYNTHETIC": "synthetic", "SIMULATED": "simulated", "MEASURED": "measured"}


def _provenance(values: pd.Series) -> str:
    classes = {str(v).strip().upper() for v in values.dropna()}
    unknown = classes - set(PROVENANCE_MAP)
    if unknown:
        raise ContractError(f"unrecognised data_class value(s) {sorted(unknown)}")
    # the least trustworthy class wins: synthetic < simulated < measured
    for cls in ("SYNTHETIC", "SIMULATED", "MEASURED"):
        if cls in classes:
            return PROVENANCE_MAP[cls]
    raise ContractError("no data_class column values; provenance unknown")


def convert_demo(source: str | Path = DEMO_SOURCE, out: str | Path | None = None) -> Path:
    source = Path(source)
    out = Path(out) if out else REPO_ROOT / "examples" / "demo_bundle"

    asset = pd.read_csv(source / "battery_asset.csv").set_index("field")["value"].to_dict()
    tel = pd.read_csv(source / "telemetry.csv")
    health = pd.read_csv(source / "health_history.csv")
    events = pd.read_csv(source / "safety_events.csv")

    chem_raw = asset["chemistry"]
    if chem_raw not in CHEMISTRY_MAP:
        raise ContractError(f"chemistry {chem_raw!r} has no explicit mapping")
    m = re.fullmatch(r"(\d+)s(\d+)p", str(asset["series_parallel_configuration"]).strip())
    if not m:
        raise ContractError("series_parallel_configuration is not of the form <n>s<m>p")

    provenance = _provenance(tel["data_class"])
    cap_tests = [
        CapacityTest(
            date=r.assessment_date, cycle_count=int(r.cycle_count),
            measured_capacity_ah=float(r.measured_capacity_Ah), method=r.assessment_method,
            provenance=PROVENANCE_MAP[str(r.data_class).upper()],
        )
        for r in health.itertuples()
    ]
    r_tests = [
        ResistanceTest(
            date=r.assessment_date, cycle_count=int(r.cycle_count),
            resistance_mohm=float(r.internal_resistance_mOhm), level="pack",
            method=r.assessment_method, provenance=PROVENANCE_MAP[str(r.data_class).upper()],
        )
        for r in health.itertuples()
    ]
    safety = [
        SafetyEvent(
            timestamp_utc=r.timestamp_utc, event_type=r.event_type, severity=r.severity,
            status=r.status, description=f"observed {r.observed_value}; threshold {r.threshold_value}",
            provenance=PROVENANCE_MAP[str(r.data_class).upper()],
        )
        for r in events.itertuples()
    ]
    meta = Metadata(
        asset_id=asset["asset_id"],
        chemistry=CHEMISTRY_MAP[chem_raw],
        rated_capacity_ah=float(asset["nominal_capacity_Ah"]),
        nominal_voltage_v=float(asset["nominal_voltage_V"]),
        min_voltage_v=float(asset["min_voltage_V"]),
        max_voltage_v=float(asset["max_voltage_V"]),
        series_cells=int(m.group(1)),
        parallel_cells=int(m.group(2)),
        data_provenance=provenance,
        current_sign_convention="unknown",
        cell_model=asset.get("cell_format"),
        cycle_count=int(health["cycle_count"].max()),
        capacity_tests=cap_tests,
        resistance_tests=r_tests,
        safety_events=safety,
        notes=str(asset.get("demo_status", "")),
        source="REVIVE-TERY demo CSV bundle (ev_battery_demo_csv_bundle.zip), converted by revive_ml.convert",
    )
    unmapped = [c for c in tel.columns if c not in TELEMETRY_MAP and c != "data_class"]
    if unmapped:
        raise ContractError(f"demo telemetry has unmapped column(s) {unmapped}")
    telemetry = tel.rename(columns=TELEMETRY_MAP)[list(TELEMETRY_MAP.values())]
    write_bundle(out, meta, telemetry, fmt="csv")
    return out
