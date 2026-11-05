"""Input data contract: a bundle directory with metadata.json and telemetry.(parquet|csv).

Schema problems raise ContractError with a message that names the offending fields.
Value problems (nulls, spikes, gaps) are NOT contract errors: data quality reports them.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Literal

import pandas as pd
import pandera.pandas as pa
from pydantic import BaseModel, ConfigDict, Field, PositiveFloat, ValidationError, model_validator

Chemistry = Literal["LFP", "NMC", "NCA"]
DataProvenance = Literal["measured", "simulated", "synthetic"]
SignConvention = Literal["discharge_negative", "discharge_positive", "unknown"]

REQUIRED_COLUMNS = ("asset_id", "timestamp_utc", "voltage_v", "current_a", "temperature_c")
OPTIONAL_COLUMNS = (
    "soc_pct",
    "min_temperature_c",
    "ambient_temperature_c",
    "power_kw",
    "operating_state",
    "bms_soh_pct",
)
# Names seen in the existing REVIVE-TERY demo data. Only used to make error messages helpful;
# they are never renamed automatically (use `revive-ml convert-demo` for that).
KNOWN_FOREIGN_NAMES = {
    "pack_voltage_V": "voltage_v",
    "pack_current_A": "current_a",
    "max_cell_temp_C": "temperature_c",
    "soh_pct": "bms_soh_pct",
    "power_kW": "power_kw",
}


class ContractError(ValueError):
    """The bundle does not satisfy the data contract."""


class _Record(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provenance: DataProvenance


class CapacityTest(_Record):
    date: date
    cycle_count: int | None = Field(default=None, ge=0)
    measured_capacity_ah: PositiveFloat
    method: str | None = None


class ResistanceTest(_Record):
    date: date
    cycle_count: int | None = Field(default=None, ge=0)
    resistance_mohm: PositiveFloat
    level: Literal["pack", "cell"] = "pack"
    method: str | None = None


class SafetyEvent(_Record):
    timestamp_utc: datetime
    event_type: str
    severity: str
    status: str | None = None
    description: str | None = None


class Metadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_id: str
    chemistry: Chemistry
    rated_capacity_ah: PositiveFloat
    nominal_voltage_v: PositiveFloat
    min_voltage_v: PositiveFloat
    max_voltage_v: PositiveFloat
    series_cells: int | None = Field(default=None, gt=0)
    parallel_cells: int | None = Field(default=None, gt=0)
    data_provenance: DataProvenance
    current_sign_convention: SignConvention = "unknown"
    cell_model: str | None = None
    cycle_count: int | None = Field(default=None, ge=0)
    capacity_tests: list[CapacityTest] = []
    resistance_tests: list[ResistanceTest] = []
    safety_events: list[SafetyEvent] = []
    notes: str | None = None
    source: str | None = None

    @model_validator(mode="after")
    def _voltages_ordered(self) -> Metadata:
        if not self.min_voltage_v < self.nominal_voltage_v < self.max_voltage_v:
            raise ValueError(
                "voltages must satisfy min_voltage_v < nominal_voltage_v < max_voltage_v, got "
                f"{self.min_voltage_v} / {self.nominal_voltage_v} / {self.max_voltage_v}"
            )
        return self

    @property
    def series(self) -> int | None:
        return self.series_cells


TELEMETRY_SCHEMA = pa.DataFrameSchema(
    {
        "asset_id": pa.Column(str, nullable=False),
        "timestamp_utc": pa.Column("datetime64[ns, UTC]", nullable=False, coerce=True),
        "voltage_v": pa.Column(float, nullable=True, coerce=True),
        "current_a": pa.Column(float, nullable=True, coerce=True),
        "temperature_c": pa.Column(float, nullable=True, coerce=True),
        "soc_pct": pa.Column(float, nullable=True, coerce=True, required=False),
        "min_temperature_c": pa.Column(float, nullable=True, coerce=True, required=False),
        "ambient_temperature_c": pa.Column(float, nullable=True, coerce=True, required=False),
        "power_kw": pa.Column(float, nullable=True, coerce=True, required=False),
        "operating_state": pa.Column(str, nullable=True, required=False),
        "bms_soh_pct": pa.Column(float, nullable=True, coerce=True, required=False),
    },
    strict=False,
)


@dataclass
class Bundle:
    meta: Metadata
    telemetry: pd.DataFrame
    path: Path | None = None
    ignored_columns: list[str] = field(default_factory=list)


def validate_telemetry(df: pd.DataFrame, asset_id: str | None = None) -> tuple[pd.DataFrame, list[str]]:
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        hints = [
            f"'{k}' looks like '{v}'" for k, v in KNOWN_FOREIGN_NAMES.items()
            if k in df.columns and v in missing
        ]
        msg = f"telemetry is missing required column(s): {', '.join(missing)}."
        if hints:
            msg += " Found " + "; ".join(hints) + ". Rename explicitly or run `revive-ml convert-demo`."
        raise ContractError(msg)
    df = df.copy()
    if not pd.api.types.is_datetime64_any_dtype(df["timestamp_utc"]):
        try:
            df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], utc=True, format="ISO8601")
        except (ValueError, TypeError) as exc:
            raise ContractError(f"timestamp_utc is not parseable as ISO-8601 UTC: {exc}") from exc
    elif df["timestamp_utc"].dt.tz is None:
        raise ContractError("timestamp_utc has no timezone; the contract requires UTC")
    df["timestamp_utc"] = df["timestamp_utc"].dt.tz_convert("UTC").astype("datetime64[ns, UTC]")
    if "operating_state" in df.columns:
        df["operating_state"] = df["operating_state"].astype("string").astype(object)
    try:
        df = TELEMETRY_SCHEMA.validate(df, lazy=True)
    except pa.errors.SchemaErrors as exc:
        cases = exc.failure_cases[["column", "check"]].drop_duplicates().to_dict("records")
        raise ContractError(f"telemetry schema errors: {cases}") from exc
    if asset_id is not None:
        others = sorted(set(df["asset_id"]) - {asset_id})
        if others:
            raise ContractError(f"telemetry contains asset_id(s) {others} not matching metadata {asset_id!r}")
    known = set(REQUIRED_COLUMNS) | set(OPTIONAL_COLUMNS)
    ignored = [c for c in df.columns if c not in known]
    return df, ignored


def load_bundle(path: str | Path) -> Bundle:
    path = Path(path)
    meta_file = path / "metadata.json"
    if not meta_file.exists():
        raise ContractError(f"{meta_file} not found: a bundle is a directory with metadata.json")
    try:
        meta = Metadata.model_validate_json(meta_file.read_text(encoding="utf-8"))
    except ValidationError as exc:
        raise ContractError(f"metadata.json invalid:\n{exc}") from exc
    if (path / "telemetry.parquet").exists():
        df = pd.read_parquet(path / "telemetry.parquet")
    elif (path / "telemetry.csv").exists():
        df = pd.read_csv(path / "telemetry.csv")
    else:
        raise ContractError(f"no telemetry.parquet or telemetry.csv in {path}")
    df, ignored = validate_telemetry(df, meta.asset_id)
    return Bundle(meta=meta, telemetry=df, path=path, ignored_columns=ignored)


def write_bundle(bundle_dir: str | Path, meta: Metadata, telemetry: pd.DataFrame,
                 fmt: Literal["parquet", "csv"] = "csv") -> Path:
    bundle_dir = Path(bundle_dir)
    bundle_dir.mkdir(parents=True, exist_ok=True)
    validate_telemetry(telemetry, meta.asset_id)
    (bundle_dir / "metadata.json").write_text(
        json.dumps(meta.model_dump(mode="json", exclude_none=True), indent=2), encoding="utf-8"
    )
    out = telemetry.copy()
    if fmt == "csv":
        out["timestamp_utc"] = pd.to_datetime(out["timestamp_utc"], utc=True).dt.strftime(
            "%Y-%m-%dT%H:%M:%S.%fZ"
        )
        out.to_csv(bundle_dir / "telemetry.csv", index=False)
    else:
        out.to_parquet(bundle_dir / "telemetry.parquet", index=False)
    return bundle_dir
