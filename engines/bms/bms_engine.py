"""REVIVE-TERY BMS engine: DuckDB access, read-only ESP32 input, and SOC/SOH maths.

It sits between the data sources (a physical ESP32 or the Test Bench's virtual battery)
and the Circuit Studio UI. Both sources produce the same Sample, so the maths doesn't
need to know where a reading came from.

MONITOR-ONLY: this module reads from the ESP32 and never sends it anything. The port is
wrapped in _ReadOnlyPort, which has no method for writing, so a control command can't be
sent by accident.
"""
from __future__ import annotations

import json
import re
import os
import math
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterator

import duckdb

# Paths come from this file's location, so the app works from any working directory.
PROJECT_ROOT = Path(__file__).resolve().parents[2]  # platform root (engines/bms -> platform)
DB_PATH = Path(os.environ.get("REVIVE_DB") or PROJECT_ROOT / "data" / "db" / "revive_tery.duckdb")

# The bundle's column names.
KEY_COLUMN = "asset_id"
TIME_COLUMN = "timestamp_utc"

# Run logs go in their own table, so a rebuild or a replay never mixes them with source data.
LOG_TABLE = "test_run_log"

# A live SOH estimate needs this much SOC change, or rounding in SOC swamps the result.
MIN_DELTA_SOC_PCT = 5.0
# Flag the data when two figures for the same quantity differ by more than this many points.
DISAGREEMENT_POINTS = 10.0
# What a DS18B20 library reports when the sensor is disconnected. It isn't a temperature.
DS18B20_DISCONNECTED_C = -127.0

# Plain "#" messages from firmware/revive_tery_esp32. Keep these in step with the sketch.
FIRMWARE_READY_MESSAGE = "# INA219 ready"
FIRMWARE_OVER_VOLTAGE_PREFIX = "# OVER"
# Firmware v1.1 status lines (boot reason, version, heartbeat, sensor addresses): information, not faults.
FIRMWARE_INFO_PREFIXES = ("# fw=", "# hb", "# boot", "# ds18b20")
# v1.1 repeats a persisting warning at most every 10 s with "(x<n>)" appended; the base text decides severity.
FIRMWARE_REPEAT_SUFFIX = re.compile(r"\s*\(x\d+\)\s*$")
SEQ_MODULUS = 2 ** 32
MAX_FIRMWARE_MESSAGE_LENGTH = 200

# DuckDB refuses to open one file with different settings at once in a single process, and
# the logger writes while the UI reads. Every database use therefore takes this lock and
# keeps its connection open only briefly.
DB_LOCK = threading.RLock()


class DatabaseUnavailable(Exception):
    """A database problem, with a message fit to show on the dashboard."""


class HardwareError(Exception):
    """A serial port problem, with a message fit to show on the dashboard."""


# ------------------------------------------------------------------------------------
# Database access
# ------------------------------------------------------------------------------------


@contextmanager
def open_db(read_only: bool = True, path: Path | None = None):
    """Open the database briefly, holding the lock until the connection is closed."""
    db_path = Path(path) if path else DB_PATH
    with DB_LOCK:
        if not db_path.is_file():
            raise DatabaseUnavailable(f"Database not found: {db_path}. Run: python src/build_relational_db.py")
        try:
            con = duckdb.connect(str(db_path), read_only=read_only)
        except duckdb.Error as exc:
            raise DatabaseUnavailable(f"Could not open {db_path.name}. Is another program using it? ({exc})") from exc
        try:
            yield con
        finally:
            con.close()


def table_columns(con: duckdb.DuckDBPyConnection, table: str) -> set[str]:
    """Lower-case column names of a table. Empty when the table doesn't exist."""
    rows = con.execute("SELECT column_name FROM information_schema.columns WHERE table_name = ?", [table]).fetchall()
    return {row[0].lower() for row in rows}


@dataclass(frozen=True)
class BatteryProfile:
    """What the database states about one battery. Anything it doesn't state stays None."""
    asset_id: str
    chemistry: str | None = None
    nominal_voltage_v: float | None = None
    min_voltage_v: float | None = None
    max_voltage_v: float | None = None
    rated_capacity_ah: float | None = None
    measured_capacity_ah: float | None = None  # From the newest capacity test in health_history.
    capacity_test_date: str | None = None
    telemetry_rows: int = 0
    is_synthetic: bool = False


def _number(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def list_battery_ids(path: Path | None = None) -> list[str]:
    """Every battery that has an asset record or telemetry, in a stable order."""
    with open_db(path=path) as con:
        ids: set[str] = set()
        if {"field", "value"} <= table_columns(con, "battery_asset"):
            ids |= {str(r[0]) for r in con.execute(f"SELECT value FROM battery_asset WHERE field = '{KEY_COLUMN}'").fetchall()}
        if KEY_COLUMN in table_columns(con, "telemetry"):
            ids |= {str(r[0]) for r in con.execute(f'SELECT DISTINCT "{KEY_COLUMN}" FROM telemetry').fetchall()}
    return sorted(ids)


def load_battery_profile(asset_id: str, path: Path | None = None) -> BatteryProfile:
    """Query DuckDB for one battery. The Circuit Studio calls this when the battery is tapped."""
    with open_db(path=path) as con:
        details: dict[str, str] = {}
        # battery_asset holds one pack as (field, value) rows. Its asset_id row says which.
        if {"field", "value"} <= table_columns(con, "battery_asset"):
            if KEY_COLUMN in table_columns(con, "battery_asset"):   # fleet layout: (asset_id, field, value)
                fetched = con.execute("SELECT field, value FROM battery_asset WHERE asset_id = ?", [asset_id]).fetchall()
            else:
                fetched = con.execute("SELECT field, value FROM battery_asset").fetchall()
            pairs = {str(k): str(v) for k, v in fetched}
            if pairs.get(KEY_COLUMN) == asset_id:
                details = pairs

        rated = _number(details.get("nominal_capacity_Ah"))
        measured = None
        test_date = None
        synthetic = "SYNTHETIC" in details.get("demo_status", "").upper()

        health_columns = table_columns(con, "health_history")
        if {KEY_COLUMN, "assessment_date", "measured_capacity_ah"} <= health_columns:
            rated_column = ', "rated_capacity_Ah"' if "rated_capacity_ah" in health_columns else ", NULL"
            row = con.execute(
                f'SELECT "measured_capacity_Ah", CAST("assessment_date" AS VARCHAR){rated_column} FROM health_history '
                f'WHERE "{KEY_COLUMN}" = ? ORDER BY "assessment_date" DESC LIMIT 1',
                [asset_id],
            ).fetchone()
            if row:
                measured, test_date = _number(row[0]), row[1]
                rated = rated if rated is not None else _number(row[2])

        rows = 0
        telemetry_columns = table_columns(con, "telemetry")
        if KEY_COLUMN in telemetry_columns:
            rows = con.execute(f'SELECT COUNT(*) FROM telemetry WHERE "{KEY_COLUMN}" = ?', [asset_id]).fetchone()[0]
        if "data_class" in telemetry_columns and not synthetic:
            synthetic = con.execute(
                f"""SELECT COUNT(*) FROM telemetry WHERE "{KEY_COLUMN}" = ? AND UPPER("data_class") LIKE '%SYNTHETIC%'""",
                [asset_id],
            ).fetchone()[0] > 0

    return BatteryProfile(
        asset_id=asset_id,
        chemistry=details.get("chemistry"),
        nominal_voltage_v=_number(details.get("nominal_voltage_V")),
        min_voltage_v=_number(details.get("min_voltage_V")),
        max_voltage_v=_number(details.get("max_voltage_V")),
        rated_capacity_ah=rated,
        measured_capacity_ah=measured,
        capacity_test_date=test_date,
        telemetry_rows=rows,
        is_synthetic=synthetic,
    )


# ------------------------------------------------------------------------------------
# SOC and SOH maths
# ------------------------------------------------------------------------------------


def calculate_soc(previous_soc_pct: float, current_a: float, delta_time_s: float, total_capacity_ah: float) -> float:
    """Coulomb counting: SOC(t) = SOC(t-1) - (Current(t) * delta_time) / Total_Capacity.

    current_a is positive while discharging, which is what the formula's minus sign assumes.
    delta_time is converted from seconds to hours so it matches a capacity in Ah, and the
    result is scaled to a percentage and kept within 0-100.
    """
    if total_capacity_ah <= 0:
        raise ValueError("total_capacity_ah must be positive")
    if delta_time_s < 0:
        raise ValueError("delta_time_s can't be negative")
    change_pct = (current_a * (delta_time_s / 3600.0)) / total_capacity_ah * 100.0
    return max(0.0, min(100.0, previous_soc_pct - change_pct))


def calculate_soh(measured_usable_capacity_ah: float, original_rated_capacity_ah: float) -> float:
    """Capacity fade: SOH = (Measured_Usable_Capacity / Original_Rated_Capacity) * 100."""
    if original_rated_capacity_ah <= 0:
        raise ValueError("original_rated_capacity_ah must be positive")
    if measured_usable_capacity_ah < 0:
        raise ValueError("measured_usable_capacity_ah can't be negative")
    return (measured_usable_capacity_ah / original_rated_capacity_ah) * 100.0


@dataclass(frozen=True)
class Sample:
    """One reading from either source, before any maths."""
    timestamp: float  # Epoch seconds. Replay uses the recorded time, hardware the arrival time.
    voltage_v: float
    current_a: float  # Signed as the source records it. BMSEngine normalises the direction.
    temperature_c: float | None = None
    reported_soc_pct: float | None = None  # An independent SOC, if the source records one.
    state: str = ""  # For example DRIVING, if the source records it.
    ambient_temperature_c: float | None = None  # Firmware v1.1 "ambient" (second DS18B20); None when absent.
    seq: int | None = None  # Firmware v1.1 line counter; None for v1.0 lines.


@dataclass(frozen=True)
class Reading:
    """A Sample plus what the engine calculated from it."""
    sample: Sample
    soc_pct: float | None
    soh_live_pct: float | None
    soh_basis: str
    discharged_ah: float
    delta_time_s: float


# How a live SOH figure was reached, from strongest to weakest evidence.
BASIS_FULL_DISCHARGE = "Measured: full discharge down to the cutoff voltage"
BASIS_PARTIAL = "Estimate: Ah discharged divided by the recorded SOC change"
BASIS_LOWER_BOUND = "At least this much: Ah discharged so far, before reaching the cutoff"
BASIS_WAITING = "Waiting for enough discharge"


class BMSEngine:
    """Turn incoming samples into SOC and SOH, updating on every reading."""

    def __init__(self, rated_capacity_ah: float | None, initial_soc_pct: float | None = None,
                 baseline_measured_ah: float | None = None, baseline_date: str | None = None,
                 cutoff_voltage_v: float | None = None, discharge_positive: bool = True):
        self.rated_capacity_ah = rated_capacity_ah
        self.baseline_measured_ah = baseline_measured_ah
        self.baseline_date = baseline_date
        self.cutoff_voltage_v = cutoff_voltage_v
        # The SOC formula needs positive current to mean discharge. Sources that record it
        # the other way, such as the demo bundle, set this to False.
        self._direction = 1.0 if discharge_positive else -1.0

        self.start_soc_pct = initial_soc_pct
        self.soc_pct = initial_soc_pct
        self.discharged_ah = 0.0
        self.samples_seen = 0
        self.soh_live_pct: float | None = None
        self.soh_basis = BASIS_WAITING
        self._full_discharge_soh: float | None = None
        self._first_reported_soc: float | None = None
        self._last_time: float | None = None
        self._skipped_steps = 0
        self._regen_rows_with_discharge_sign = 0
        self._largest_soc_gap = 0.0

    def process(self, sample: Sample) -> Reading:
        self.samples_seen += 1
        delta_time_s = 0.0
        if self._last_time is not None:
            delta_time_s = sample.timestamp - self._last_time
            if delta_time_s < 0:  # Out-of-order data can't be integrated, so this step is skipped.
                self._skipped_steps += 1
                delta_time_s = 0.0
        self._last_time = sample.timestamp

        if self._first_reported_soc is None:
            self._first_reported_soc = sample.reported_soc_pct
        # With no starting SOC given, use the source's own. Never assume a full battery.
        if self.soc_pct is None and sample.reported_soc_pct is not None:
            self.soc_pct = sample.reported_soc_pct
            self.start_soc_pct = sample.reported_soc_pct

        discharge_current_a = sample.current_a * self._direction
        if sample.state.upper().startswith("REGEN") and discharge_current_a > 0:
            self._regen_rows_with_discharge_sign += 1

        self.discharged_ah += discharge_current_a * delta_time_s / 3600.0
        if self.soc_pct is not None and self.rated_capacity_ah:
            self.soc_pct = calculate_soc(self.soc_pct, discharge_current_a, delta_time_s, self.rated_capacity_ah)
        if self.soc_pct is not None and sample.reported_soc_pct is not None:
            self._largest_soc_gap = max(self._largest_soc_gap, abs(self.soc_pct - sample.reported_soc_pct))

        self._update_live_soh(sample)
        return Reading(sample, self.soc_pct, self.soh_live_pct, self.soh_basis, self.discharged_ah, delta_time_s)

    def _update_live_soh(self, sample: Sample) -> None:
        """Recalculate SOH from the charge counted so far, with the formula in calculate_soh.

        Usable capacity is only truly measured by a full discharge, so each figure carries a
        basis saying how far it can be trusted.
        """
        if not self.rated_capacity_ah or self.discharged_ah <= 0:
            return

        reached_cutoff = (
            self.cutoff_voltage_v is not None and sample.voltage_v <= self.cutoff_voltage_v and bool(self.start_soc_pct)
        )
        if reached_cutoff and self._full_discharge_soh is None:
            # Scales for a start below 100%: Ah counted, over the share of the pack that was used.
            capacity_ah = self.discharged_ah / (self.start_soc_pct / 100.0)
            self._full_discharge_soh = calculate_soh(capacity_ah, self.rated_capacity_ah)
        if self._full_discharge_soh is not None:
            self.soh_live_pct = self._full_discharge_soh
            self.soh_basis = BASIS_FULL_DISCHARGE
            return

        if self._first_reported_soc is not None and sample.reported_soc_pct is not None:
            delta_soc = self._first_reported_soc - sample.reported_soc_pct
            if delta_soc >= MIN_DELTA_SOC_PCT:
                capacity_ah = self.discharged_ah / (delta_soc / 100.0)
                self.soh_live_pct = calculate_soh(capacity_ah, self.rated_capacity_ah)
                self.soh_basis = BASIS_PARTIAL
            return

        # No independent SOC. The pack has delivered at least this much, so it's a lower bound.
        self.soh_live_pct = calculate_soh(self.discharged_ah, self.rated_capacity_ah)
        self.soh_basis = BASIS_LOWER_BOUND

    def baseline_soh(self) -> float | None:
        if self.baseline_measured_ah is None or not self.rated_capacity_ah:
            return None
        return calculate_soh(self.baseline_measured_ah, self.rated_capacity_ah)

    def final_soh(self) -> tuple[float | None, str]:
        """The SOH to base a decision on, and where it came from. Strongest evidence wins."""
        if self._full_discharge_soh is not None:
            return self._full_discharge_soh, "Full discharge measured in this test"
        baseline = self.baseline_soh()
        if baseline is not None:
            date = f" on {self.baseline_date}" if self.baseline_date else ""
            return baseline, f"Capacity test recorded in the database{date}"
        if self.soh_basis == BASIS_PARTIAL:
            return self.soh_live_pct, "Estimate from this test's recorded SOC change"
        return None, "No capacity measurement: discharge to the cutoff voltage to measure one"

    def data_flags(self) -> list[str]:
        """Plain statements of where the incoming data disagrees with itself."""
        flags = []
        if self._regen_rows_with_discharge_sign:
            count = self._regen_rows_with_discharge_sign
            flags.append(f"{count} regenerative braking row(s) have the same current sign as discharging.")
        if self._largest_soc_gap > DISAGREEMENT_POINTS:
            flags.append(
                f"Coulomb-counted SOC drifted up to {self._largest_soc_gap:.0f} points from the recorded SOC, "
                "so the recorded current doesn't explain the recorded SOC."
            )
        baseline = self.baseline_soh()
        if baseline is not None and self.soh_basis == BASIS_PARTIAL and self.soh_live_pct is not None:
            if abs(self.soh_live_pct - baseline) > DISAGREEMENT_POINTS:
                flags.append(
                    f"The live SOH estimate ({self.soh_live_pct:.1f}%) disagrees with the recorded capacity test "
                    f"({baseline:.1f}%). The decision uses the capacity test."
                )
        if self._skipped_steps:
            flags.append(f"{self._skipped_steps} out-of-order reading(s) were left out of the charge count.")
        return flags


# ------------------------------------------------------------------------------------
# ESP32 input: strictly read-only
# ------------------------------------------------------------------------------------


class _ReadOnlyPort:
    """The only access the rest of this module has to the port. It has no write method."""

    def __init__(self, port):
        self._port = port

    def read_line(self) -> bytes:
        return self._port.readline()

    def close(self) -> None:
        self._port.close()


@dataclass(frozen=True)
class PortInfo:
    device: str
    description: str
    is_bluetooth: bool
    is_usb: bool


def list_serial_port_details() -> list[PortInfo]:
    """Available COM ports with what they are. Empty if pyserial isn't installed.

    Windows often lists several Bluetooth ports, which are never the ESP32's USB connection.
    USB ports come first, then in number order, so COM10 follows COM9.
    """
    try:
        from serial.tools import list_ports
    except ImportError:
        return []
    details = []
    for port in list_ports.comports():
        description = (port.description or port.device).replace(f" ({port.device})", "")
        bluetooth = "bluetooth" in description.lower() or "BTHENUM" in (port.hwid or "").upper()
        details.append(PortInfo(port.device, description, bluetooth, port.vid is not None and not bluetooth))

    def order(info: PortInfo):
        digits = "".join(ch for ch in info.device if ch.isdigit())
        return (not info.is_usb, info.is_bluetooth, int(digits) if digits else 0, info.device)

    return sorted(details, key=order)


def list_serial_ports() -> list[str]:
    """Available COM port names."""
    return [info.device for info in list_serial_port_details()]


def open_esp32_port(port: str, baudrate: int = 115200, serial_factory: Callable | None = None) -> _ReadOnlyPort:
    """Open the ESP32's COM port for reading. serial_factory lets tests use a fake port."""
    if serial_factory is None:
        try:
            import serial
        except ImportError as exc:
            raise HardwareError("pyserial isn't installed. Run: python -m pip install -r src/requirements.txt") from exc
        serial_factory = serial.Serial
        serial_error = serial.SerialException
    else:
        serial_error = OSError

    device = serial_factory()
    device.port = port
    device.baudrate = baudrate
    device.timeout = 1.0  # Lets the read loop notice a stop request about once a second.
    # Most ESP32 boards reset when a port is opened with these lines raised. Keeping them
    # low means monitoring doesn't restart the board. No data is sent to it.
    device.dtr = False
    device.rts = False
    try:
        device.open()
    except (serial_error, OSError) as exc:
        known = ", ".join(list_serial_ports()) or "none found"
        raise HardwareError(f"Could not open {port}: {exc}. Available ports: {known}.") from exc
    return _ReadOnlyPort(device)


def crc8(data: bytes) -> int:
    """CRC-8 of firmware v1.1: polynomial 0x07, init 0x00, no reflection, no final xor."""
    crc = 0
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = ((crc << 1) ^ 0x07) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
    return crc


def line_crc_ok(raw: bytes) -> bool | None:
    """True/False when the line carries a "crc" (computed over the bytes from "{" up to ',"crc"'); None without one."""
    text = raw.decode("utf-8", errors="replace").strip()
    cut = text.rfind(',"crc"')
    if cut < 0:
        return None
    m = re.match(r',"crc"\s*:\s*"([0-9A-Fa-f]{2})"\s*}\s*$', text[cut:])
    if not m:
        return False
    return int(m.group(1), 16) == crc8(text[:cut].encode("utf-8"))


def parse_telemetry_line(raw: bytes, now: float) -> Sample | None:
    """Turn one JSON line into a Sample, or None if it isn't valid telemetry.

    Expected from the ESP32: {"voltage": 3.71, "current": 0.52, "temperature": 28.4}
    Firmware v1.1 adds optional "ambient", "seq", "t_ms" and "crc"; a line whose crc is wrong is rejected.
    Boot messages and half-received lines are normal on a serial port, so they're skipped.
    """
    try:
        data = json.loads(raw.decode("utf-8", errors="strict"))
        voltage = _number(data["voltage"])
        current = _number(data["current"])
    except (UnicodeDecodeError, ValueError, KeyError, TypeError):
        return None
    if voltage is None or current is None:
        return None
    if "crc" in data and line_crc_ok(raw) is not True:
        return None
    temperature = _number(data.get("temperature"))
    if temperature == DS18B20_DISCONNECTED_C:
        temperature = None
    ambient = _number(data.get("ambient"))
    if ambient == DS18B20_DISCONNECTED_C:
        ambient = None
    seq = data.get("seq")
    seq = int(seq) if isinstance(seq, (int, float)) and not isinstance(seq, bool) and seq >= 0 else None
    return Sample(timestamp=now, voltage_v=voltage, current_a=current, temperature_c=temperature,
                  ambient_temperature_c=ambient, seq=seq)


def firmware_message_severity(text: str) -> str:
    """How serious a "#" line from the firmware is: info, warning or critical.

    Only the known all-clear counts as info. A message this code doesn't recognise is
    treated as a warning, because an unknown message from a monitor shouldn't be ignored.
    """
    text = FIRMWARE_REPEAT_SUFFIX.sub("", text)
    if text == FIRMWARE_READY_MESSAGE or text.startswith(FIRMWARE_INFO_PREFIXES):
        return "info"
    if text.startswith(FIRMWARE_OVER_VOLTAGE_PREFIX):
        return "critical"
    return "warning"


@dataclass
class SerialStats:
    """What's happening on the connection, so a silent, noisy or faulty link is visible."""
    good_lines: int = 0
    bad_lines: int = 0  # Boot text and half-received lines. Normal in small numbers.
    message_lines: int = 0  # Plain "#" messages from the firmware.
    last_reading_at: float | None = None  # On the source's clock, which a simulation can run fast.
    last_reading_wall: float | None = None  # Real time. Staleness is judged on this one.
    last_fault: str = ""  # Kept after readings resume, so a brief fault isn't lost.
    last_fault_severity: str = ""
    last_fault_at: float | None = None
    fault_counts: dict[str, int] = field(default_factory=dict)
    crc_errors: int = 0  # Lines whose crc did not match: skipped, never logged as a measurement.
    dropped_lines: int = 0  # Gaps in the firmware's seq counter (lines lost on the way).
    last_seq: int | None = None

    def note_seq(self, seq: int | None) -> None:
        """Count lines missing between consecutive seq values. A restart (seq back near 0) is not a loss."""
        if seq is None:
            return
        if self.last_seq is not None:
            gap = (seq - self.last_seq) % SEQ_MODULUS
            if 1 < gap < SEQ_MODULUS // 2:
                self.dropped_lines += gap - 1
        self.last_seq = seq

    def record_message(self, raw: bytes, now: float) -> None:
        self.message_lines += 1
        text = raw.decode("utf-8", errors="replace").strip()[:MAX_FIRMWARE_MESSAGE_LENGTH]
        severity = firmware_message_severity(text)
        if severity == "info":
            return
        self.last_fault = text.lstrip("# ")
        self.last_fault_severity = severity
        self.last_fault_at = now
        # a throttled repeat "... (x7)" stands for 7 occurrences of the same base message
        m = re.search(r"\(x(\d+)\)\s*$", self.last_fault)
        base = FIRMWARE_REPEAT_SUFFIX.sub("", self.last_fault)
        self.fault_counts[base] = self.fault_counts.get(base, 0) + (int(m.group(1)) if m else 1)

    @property
    def fault_is_active(self) -> bool:
        """True when the newest thing the firmware sent is a fault and not a reading."""
        if self.last_fault_at is None:
            return False
        return self.last_reading_at is None or self.last_fault_at >= self.last_reading_at


def read_esp32_telemetry(port: str, baudrate: int = 115200, stop_event: threading.Event | None = None,
                         serial_factory: Callable | None = None, stats: SerialStats | None = None,
                         clock: Callable[[], float] = time.time) -> Iterator[Sample]:
    """Yield live readings from the ESP32 until stopped. Monitor-only: nothing is ever sent."""
    stats = stats if stats is not None else SerialStats()
    connection = open_esp32_port(port, baudrate, serial_factory)
    try:
        while stop_event is None or not stop_event.is_set():
            try:
                raw = connection.read_line()
            except OSError as exc:  # pyserial's SerialException is an OSError.
                raise HardwareError(f"Lost the connection to {port}: {exc}") from exc
            if not raw:
                continue  # A timeout with no data. Loop round and check for a stop request.
            now = clock()
            if raw.lstrip().startswith(b"#"):
                stats.record_message(raw, now)  # Faults and status text, not telemetry.
                continue
            if line_crc_ok(raw) is False:
                stats.crc_errors += 1  # Corrupted on the way: skipped, never logged as a measurement.
                continue
            sample = parse_telemetry_line(raw, now)
            if sample is None:
                stats.bad_lines += 1
                continue
            stats.note_seq(sample.seq)
            stats.good_lines += 1
            stats.last_reading_at = now
            stats.last_reading_wall = time.time()
            yield sample
    finally:
        connection.close()


# ------------------------------------------------------------------------------------
# Logging readings to DuckDB
# ------------------------------------------------------------------------------------


@dataclass
class TelemetryLogger:
    """Store a test's readings in test_run_log, batched so a slow disk can't hold up a run.

    Every row records its source and data class, so simulated and real readings can't be
    confused later. If the database is busy, rows stay buffered and are tried again.
    """
    run_id: str
    source: str
    asset_id: str
    data_class: str
    path: Path | None = None
    flush_every: int = 25
    flush_seconds: float = 2.0
    rows_written: int = 0
    last_error: str = ""
    _buffer: list = field(default_factory=list)
    _last_flush: float = 0.0

    def log(self, reading: Reading) -> None:
        s = reading.sample
        self._buffer.append((
            self.run_id, s.timestamp, self.source, self.asset_id, self.data_class, s.voltage_v, s.current_a,
            s.temperature_c, reading.soc_pct, reading.soh_live_pct, reading.soh_basis,
            s.seq, None, s.ambient_temperature_c, (True if s.seq is not None else None),
        ))
        now = time.monotonic()
        if len(self._buffer) >= self.flush_every or now - self._last_flush >= self.flush_seconds:
            self._last_flush = now
            self.flush()

    def flush(self) -> None:
        if not self._buffer:
            return
        try:
            with open_db(read_only=False, path=self.path) as con:
                con.execute(
                    f"""CREATE TABLE IF NOT EXISTS {LOG_TABLE} (
                        run_id VARCHAR, logged_at TIMESTAMPTZ, source VARCHAR, asset_id VARCHAR, data_class VARCHAR,
                        voltage_v DOUBLE, current_a DOUBLE, temperature_c DOUBLE, soc_pct DOUBLE,
                        soh_live_pct DOUBLE, soh_basis VARCHAR)"""
                )
                # firmware v1.1 columns (additive; rows from older runs stay NULL). t_ms is not carried by Sample.
                for col, typ in (("seq", "BIGINT"), ("t_ms", "BIGINT"), ("ambient_c", "DOUBLE"), ("crc_ok", "BOOLEAN")):
                    con.execute(f"ALTER TABLE {LOG_TABLE} ADD COLUMN IF NOT EXISTS {col} {typ}")
                con.executemany(
                    f"INSERT INTO {LOG_TABLE} (run_id, logged_at, source, asset_id, data_class, voltage_v, current_a, "
                    "temperature_c, soc_pct, soh_live_pct, soh_basis, seq, t_ms, ambient_c, crc_ok) "
                    "VALUES (?, to_timestamp(?), ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", self._buffer
                )
        except (DatabaseUnavailable, duckdb.Error) as exc:
            self.last_error = str(exc)
            return
        self.rows_written += len(self._buffer)
        self._buffer.clear()
        self.last_error = ""
