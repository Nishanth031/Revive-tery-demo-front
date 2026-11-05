"""REVIVE-TERY test runs: one controller that feeds readings through the BMS engine and logs them.

Shared by the Dash dashboard (src/app.py) and the backend API (backend/revive_api). It has no
web-framework code, so both front ends drive the same logic. The controller holds the active
battery and the current test. One per server, for local use.

MONITOR-ONLY: nothing here writes to the ESP32. Hardware readings come through
bms_engine.read_esp32_telemetry, whose port wrapper has no write method.
"""
from __future__ import annotations

import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, replace
from datetime import datetime, timezone

from bms_engine import (
    BMSEngine, BatteryProfile, DatabaseUnavailable, HardwareError, Reading, SerialStats, TelemetryLogger,
    list_battery_ids, load_battery_profile, read_esp32_telemetry,
)
from esp32_sim import FAULT_NONE, FAULTS, SimulatedESP32, SimulationSettings
from test_bench import BUNDLE_DISCHARGE_POSITIVE, VirtualBattery, get_decision_for_ui

HISTORY_LIMIT = 2000
HARDWARE_BATTERY_ID = "HARDWARE-BENCH"

SOURCE_VIRTUAL = "virtual"
SOURCE_HARDWARE = "hardware"
# A simulated ESP32 runs through the hardware path, so it's a choice on the page but not a
# separate source inside the controller. The controller tells them apart with its simulated flag.
SOURCE_SIMULATED = "simulated"
SIMULATED_BATTERY_ID = "SIMULATED-CELL"
SPEED_LIMITS = (1.0, 600.0)
SIMULATED_RATED_AH = 2.0  # Filled in when you pick the simulator, for a cell whose true capacity is 1.8 Ah.
SIMULATED_CUTOFF_V = 3.0
SIM_MAX_LOAD_A = 3.0


@dataclass(frozen=True)
class HardwareSettings:
    port: str
    baudrate: int
    rated_capacity_ah: float
    start_soc_pct: float
    cutoff_voltage_v: float | None
    discharge_positive: bool


class RunController:
    """Holds the active battery and the current test. One per server, for local use."""

    def __init__(self):
        self.simulated = False
        self.sim: SimulatedESP32 | None = None
        self.lock = threading.Lock()
        self.battery_ids: list[str] = []
        self.profile: BatteryProfile | None = None
        self.readings: deque[Reading] = deque(maxlen=HISTORY_LIMIT)
        self.status = "idle"  # idle, running, finished, stopped or error.
        self.source = SOURCE_VIRTUAL
        self.notice = ""
        self.error = ""
        self.decision: dict | None = None
        self.log_note = ""
        self.serial_stats = SerialStats()
        self.run_started_at = 0.0
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self.loaded = False

    @property
    def running(self) -> bool:
        return self.status == "running"

    def load_initial_battery(self) -> None:
        """Load the first battery the first time the page asks for data."""
        with self.lock:
            if self.loaded:
                return
            self.loaded = True
        try:
            ids = list_battery_ids()
            profile = load_battery_profile(ids[0]) if ids else None
        except DatabaseUnavailable as exc:
            with self.lock:
                self.error = str(exc)
                self.loaded = False  # Try again on the next refresh, once the file is there.
            return
        with self.lock:
            self.battery_ids = ids
            self.profile = profile
            self.error = "" if ids else "The database has no batteries yet. Run: python src/build_relational_db.py"

    def switch_battery(self) -> None:
        """Battery tapped: query DuckDB, move to the next battery and reset the dashboard."""
        if self.running:
            with self.lock:
                self.notice = "Stop the test before switching battery."
            return
        try:
            ids = list_battery_ids()
            if not ids:
                raise DatabaseUnavailable("The database has no batteries yet.")
            current = self.profile.asset_id if self.profile else None
            position = ids.index(current) if current in ids else -1
            next_id = ids[(position + 1) % len(ids)]
            profile = load_battery_profile(next_id)
        except DatabaseUnavailable as exc:
            with self.lock:
                self.error = str(exc)
            return
        with self.lock:
            self.battery_ids = ids
            self.profile = profile
            self.readings.clear()
            self.decision = None
            self.log_note = ""
            self.error = ""
            self.status = "idle"
            self.source = SOURCE_VIRTUAL
            self.simulated = False
            self.sim = None
            self.serial_stats = SerialStats()
            if len(ids) == 1:
                self.notice = f"Reloaded {next_id} from DuckDB. It's the only battery in the database."
            else:
                self.notice = f"Loaded {next_id} from DuckDB ({ids.index(next_id) + 1} of {len(ids)})."

    def select_battery(self, asset_id: str) -> bool:
        """Make asset_id the battery for the next virtual replay. False if a test is running or it is unknown."""
        if self.running:
            with self.lock:
                self.notice = "Stop the test before switching battery."
            return False
        try:
            ids = list_battery_ids()
            if asset_id not in ids:
                return False
            profile = load_battery_profile(asset_id)
        except DatabaseUnavailable as exc:
            with self.lock:
                self.error = str(exc)
            return False
        with self.lock:
            self.battery_ids = ids
            self.profile = profile
            self.readings.clear()
            self.decision = None
            self.log_note = ""
            self.error = ""
            self.status = "idle"
            self.source = SOURCE_VIRTUAL
            self.simulated = False
            self.sim = None
            self.serial_stats = SerialStats()
            self.notice = f"Loaded {asset_id} from DuckDB."
        return True

    def _begin(self, source: str) -> str:
        with self.lock:
            self.readings.clear()
            self.decision = None
            self.error = ""
            self.notice = ""
            self.log_note = ""
            self.source = source
            self.simulated = False
            self.sim = None
            self.status = "running"
            self.serial_stats = SerialStats()
            self.run_started_at = time.time()
            self._stop_event = threading.Event()
        return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:6]

    def start_virtual(self, delay_s: float) -> None:
        profile = self.profile
        if self.running:
            return
        if profile is None:
            with self.lock:
                self.notice = "No battery is loaded."
            return
        if not profile.telemetry_rows:
            with self.lock:
                self.notice = f"{profile.asset_id} has no telemetry to replay."
            return
        run_id = self._begin(SOURCE_VIRTUAL)
        engine = BMSEngine(
            rated_capacity_ah=profile.rated_capacity_ah,
            baseline_measured_ah=profile.measured_capacity_ah,
            baseline_date=profile.capacity_test_date,
            discharge_positive=BUNDLE_DISCHARGE_POSITIVE,
        )
        data_class = "SYNTHETIC" if profile.is_synthetic else "RECORDED"
        logger = TelemetryLogger(run_id, "virtual_replay", profile.asset_id, data_class)
        samples = VirtualBattery(profile.asset_id, delay_s=delay_s, stop_event=self._stop_event)
        self._launch(samples, engine, logger)

    def start_hardware(self, settings: HardwareSettings) -> None:
        if self.running:
            return
        run_id = self._begin(SOURCE_HARDWARE)
        engine = BMSEngine(
            rated_capacity_ah=settings.rated_capacity_ah,
            initial_soc_pct=settings.start_soc_pct,
            cutoff_voltage_v=settings.cutoff_voltage_v,
            discharge_positive=settings.discharge_positive,
        )
        logger = TelemetryLogger(run_id, "esp32_hardware", HARDWARE_BATTERY_ID, "MEASURED")
        samples = read_esp32_telemetry(
            settings.port, settings.baudrate, stop_event=self._stop_event, stats=self.serial_stats,
        )
        self._launch(samples, engine, logger)

    def start_simulated(self, settings: HardwareSettings, sim_settings: SimulationSettings, fault: str = FAULT_NONE) -> None:
        """Run the software ESP32 through the same path as a real board, and log it as SIMULATED."""
        if self.running:
            return
        run_id = self._begin(SOURCE_HARDWARE)
        sim = SimulatedESP32(sim_settings)
        sim.set_fault(fault)
        with self.lock:
            self.simulated = True
            self.sim = sim
        engine = BMSEngine(
            rated_capacity_ah=settings.rated_capacity_ah,
            initial_soc_pct=sim_settings.start_soc_pct,
            cutoff_voltage_v=settings.cutoff_voltage_v,
            discharge_positive=True,  # The simulated wiring reads discharge as positive, like the real kit.
        )
        logger = TelemetryLogger(run_id, "esp32_simulated", SIMULATED_BATTERY_ID, "SIMULATED")
        stop_event = self._stop_event

        def samples():
            """Read through the real hardware path. The test ends when the load has emptied the
            cell, like a bench run, rather than waiting for the user to press Stop."""
            readings = read_esp32_telemetry(
                "SIMULATED", 115200, stop_event=stop_event, stats=self.serial_stats,
                serial_factory=lambda: sim, clock=sim.clock,
            )
            try:
                for sample in readings:
                    yield sample
                    if sim.complete:
                        return
            finally:
                readings.close()

        self._launch(samples(), engine, logger)

    def set_sim_fault(self, fault: str) -> None:
        """Inject or clear a fault while the simulated test is running."""
        with self.lock:
            sim = self.sim
        if sim is not None and fault in FAULTS:
            sim.set_fault(fault)

    def _launch(self, samples, engine: BMSEngine, logger: TelemetryLogger) -> None:
        self._thread = threading.Thread(target=self._run, args=(samples, engine, logger), daemon=True)
        self._thread.start()

    def _run(self, samples, engine: BMSEngine, logger: TelemetryLogger) -> None:
        """Feed readings through the engine and logger until the source ends or is stopped."""
        final_status = "finished"
        error = ""
        try:
            for sample in samples:
                reading = engine.process(sample)
                logger.log(reading)
                with self.lock:
                    self.readings.append(reading)
            if self._stop_event.is_set():
                final_status = "stopped"
        except (DatabaseUnavailable, HardwareError) as exc:
            final_status = "error"
            error = str(exc)
        except Exception as exc:  # A background thread has no one to report to but the page.
            final_status = "error"
            error = f"The test stopped unexpectedly: {exc}"
        logger.flush()
        note = f"{logger.rows_written} readings logged to DuckDB, table test_run_log (run {logger.run_id})."
        if logger.last_error:
            note = f"Some readings couldn't be logged, because the database was busy: {logger.last_error}"
        with self.lock:
            self.status = final_status
            self.error = error
            self.log_note = note
            self.decision = get_decision_for_ui(engine) if engine.samples_seen else None
            if self.decision:
                self.decision["flags"] = [*self.decision["flags"], *fault_flags(self.serial_stats)]
                if self.simulated:
                    self.decision["flags"].insert(
                        0, "This result comes from a software simulation of a made-up cell, not from a real battery."
                    )

    def stop(self) -> None:
        self._stop_event.set()

    def snapshot(self) -> dict:
        """A consistent copy for the page to draw, so a reading can't change mid-draw."""
        with self.lock:
            return {
                "status": self.status,
                "source": self.source,
                "profile": self.profile,
                "readings": list(self.readings),
                "decision": self.decision,
                "notice": self.notice,
                "error": self.error,
                "log_note": self.log_note,
                "battery_count": len(self.battery_ids),
                "good_lines": self.serial_stats.good_lines,
                "bad_lines": self.serial_stats.bad_lines,
                "message_lines": self.serial_stats.message_lines,
                "stats": replace(self.serial_stats, fault_counts=dict(self.serial_stats.fault_counts)),
                "run_started_at": self.run_started_at,
                "simulated": self.simulated,
            }


def fault_flags(stats: SerialStats) -> list[str]:
    """Faults for the final result. Readings were withheld, so the charge count is affected."""
    if not stats.fault_counts:
        return []
    listed = "; ".join(f"{message} ({count} time{'s' if count != 1 else ''})" for message, count in stats.fault_counts.items())
    return [
        f"The firmware reported faults during this test: {listed}. "
        "No readings were sent while these were active, so SOC and SOH across those periods are approximate."
    ]
