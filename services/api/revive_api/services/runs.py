"""Test runs: the shared RunController (virtual replay, simulated ESP32, real ESP32) behind JSON.

MONITOR-ONLY, as everywhere in REVIVE-TERY: the backend reads from the ESP32 and never sends it anything.
"""
from __future__ import annotations

import time
from dataclasses import asdict
from typing import Any

from .. import settings
from bms_engine import Reading, list_serial_port_details
from esp32_sim import FAULTS, SimulationSettings
from run_controller import SOURCE_HARDWARE, HardwareSettings, RunController

from ..schemas import RunStartIn

controller = RunController()


class RunConflict(RuntimeError):
    """A run is already in progress, or the request cannot start one."""


def reading_dict(r: Reading) -> dict[str, Any]:
    s = r.sample
    return {"timestamp": s.timestamp, "voltage_v": s.voltage_v, "current_a": s.current_a,
            "temperature_c": s.temperature_c, "reported_soc_pct": s.reported_soc_pct, "state": s.state,
            "soc_pct": r.soc_pct, "soh_live_pct": r.soh_live_pct, "soh_basis": r.soh_basis,
            "discharged_ah": r.discharged_ah, "delta_time_s": r.delta_time_s}


def snapshot_json(since_ts: float | None = None, tail: int = 600) -> dict[str, Any]:
    """The run as the front end draws it. since_ts returns only readings newer than that timestamp."""
    controller.load_initial_battery()
    snap = controller.snapshot()
    readings = snap["readings"]
    chosen = [x for x in readings if x.sample.timestamp > since_ts] if since_ts is not None else readings[-tail:]
    stats = snap["stats"]
    now = time.time()
    stale = (snap["status"] == "running" and snap["source"] == SOURCE_HARDWARE
             and stats.last_reading_wall is not None and now - stats.last_reading_wall > settings.STALE_READING_S)
    return {
        "status": snap["status"], "running": snap["status"] == "running", "source": snap["source"],
        "mode": "simulated" if snap["simulated"] else snap["source"],     # virtual | simulated | hardware
        "simulated": snap["simulated"], "stale": stale, "server_time": now,
        "battery": asdict(snap["profile"]) if snap["profile"] else None,
        "battery_count": snap["battery_count"],
        "notice": snap["notice"], "error": snap["error"], "log_note": snap["log_note"],
        "decision": snap["decision"], "run_started_at": snap["run_started_at"],
        "counts": {"good_lines": stats.good_lines, "bad_lines": stats.bad_lines, "message_lines": stats.message_lines,
                   "readings_held": len(readings)},
        "fault": {"active": stats.fault_is_active, "last": stats.last_fault, "severity": stats.last_fault_severity,
                  "counts": dict(stats.fault_counts)},
        "readings": [reading_dict(x) for x in chosen],
    }


def start(req: RunStartIn) -> dict[str, Any]:
    if controller.running:
        raise RunConflict("A test is already running. Stop it first.")
    if req.source == "virtual":
        if req.battery_id and not controller.select_battery(req.battery_id):
            raise RunConflict(f"Could not load battery {req.battery_id!r}. {controller.snapshot()['notice']}")
        controller.load_initial_battery()
        controller.start_virtual(req.delay_s)
    elif req.source == "hardware":
        h = req.hardware
        assert h is not None
        controller.start_hardware(HardwareSettings(h.port, h.baudrate, h.rated_capacity_ah, h.start_soc_pct,
                                                   h.cutoff_voltage_v, h.discharge_positive))
    else:
        s = req.simulation
        controller.start_simulated(
            HardwareSettings("SIMULATED", 115200, s.rated_capacity_ah, s.start_soc_pct, s.cutoff_voltage_v, True),
            SimulationSettings(true_capacity_ah=s.true_capacity_ah, start_soc_pct=s.start_soc_pct,
                               load_current_a=s.load_current_a, speed=s.speed, seed=s.seed),
            s.fault,
        )
    snap = controller.snapshot()
    if snap["status"] != "running":
        # start_* refuse quietly (no battery, no telemetry); the reason is in the notice
        raise RunConflict(snap["notice"] or snap["error"] or "The test did not start.")
    return snapshot_json()


def stop() -> dict[str, Any]:
    controller.stop()
    return snapshot_json()


def set_fault(fault: str) -> None:
    if not controller.snapshot()["simulated"] or not controller.running:
        raise RunConflict("Faults can only be injected while a simulated ESP32 test is running.")
    controller.set_sim_fault(fault)


def faults() -> list[dict[str, str]]:
    return [{"id": k, "label": v} for k, v in FAULTS.items()]


def ports() -> list[dict[str, Any]]:
    return [asdict(p) for p in list_serial_port_details()]
