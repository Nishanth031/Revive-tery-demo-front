"""Request models. Limits mirror the ones the Dash dashboard enforces (src/run_controller.py)."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from . import settings  # noqa: F401
from esp32_sim import FAULT_NONE, FAULTS
from run_controller import SIM_MAX_LOAD_A, SIMULATED_CUTOFF_V, SIMULATED_RATED_AH, SPEED_LIMITS


class HardwareIn(BaseModel):
    port: str = Field(min_length=1)
    baudrate: int = Field(115200, gt=0)
    rated_capacity_ah: float = Field(gt=0)
    start_soc_pct: float = Field(100.0, ge=0, le=100)
    cutoff_voltage_v: float | None = Field(None, gt=0)
    discharge_positive: bool = True


class SimulationIn(BaseModel):
    true_capacity_ah: float = Field(1.8, ge=0.05)
    load_current_a: float = Field(1.0, ge=0.05, le=SIM_MAX_LOAD_A)
    speed: float = Field(60.0, ge=SPEED_LIMITS[0], le=SPEED_LIMITS[1])
    start_soc_pct: float = Field(100.0, ge=0, le=100)
    rated_capacity_ah: float = Field(SIMULATED_RATED_AH, gt=0)
    cutoff_voltage_v: float = Field(SIMULATED_CUTOFF_V, gt=0)
    seed: int | None = None
    fault: str = FAULT_NONE

    @field_validator("fault")
    @classmethod
    def _known_fault(cls, v: str) -> str:
        if v not in FAULTS:
            raise ValueError(f"unknown fault {v!r}; choose one of {sorted(FAULTS)}")
        return v


class RunStartIn(BaseModel):
    source: Literal["virtual", "hardware", "simulated"]
    battery_id: str | None = None        # virtual replay: which database battery to replay
    delay_s: float = Field(1.0, ge=0.05, le=10)
    hardware: HardwareIn | None = None
    simulation: SimulationIn = SimulationIn()

    @model_validator(mode="after")
    def _hardware_needs_settings(self) -> "RunStartIn":
        if self.source == "hardware" and self.hardware is None:
            raise ValueError("source 'hardware' needs a 'hardware' block (port, rated_capacity_ah, ...)")
        return self


class FaultIn(BaseModel):
    fault: str

    @field_validator("fault")
    @classmethod
    def _known_fault(cls, v: str) -> str:
        if v not in FAULTS:
            raise ValueError(f"unknown fault {v!r}")
        return v


class SpecIn(BaseModel):
    """What an uploaded file cannot say about the battery. Ignored for batteries that have asset records."""
    chemistry: Literal["LFP", "NMC", "NCA"] = "LFP"
    series_cells: int = Field(1, ge=1)
    parallel_cells: int = Field(1, ge=1)
    rated_capacity_ah: float | None = Field(None, gt=0)
    nominal_voltage_v: float | None = Field(None, gt=0)


class AssessIn(BaseModel):
    battery_id: str = Field(min_length=1)
    engine: Literal["auto", "full", "lite"] = "auto"
    spec: SpecIn = SpecIn()
    workloads: dict[str, Any] | None = None
    # database packs only: 'dense' = densified SYNTHETIC series (engines/database/import_fleet.py), 'original' = the
    # pack's own recorded rows
    telemetry_source: Literal["dense", "original"] = "dense"
