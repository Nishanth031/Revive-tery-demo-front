"""A software ESP32 and circuit, for running the whole system with no hardware.

SimulatedESP32 stands in for the serial port. It models the bench circuit (a 1S Li-ion cell, a
constant-current test load, an INA219 and a DS18B20) and runs the same decisions as
firmware/revive_tery_esp32: the same JSON lines, the same "#" fault messages, the same limits and
the same retry timing. bms_engine.read_esp32_telemetry reads it exactly as it would a real port.

The readings are generated, not measured. The battery is a made-up cell whose true capacity you
choose, so a full discharge produces a known SOH to check the engine against. Everything it
produces must be labelled as simulated wherever it is shown or stored.

MONITOR-ONLY: like the real monitor, this has no write method, so nothing can be sent to it.
"""
from __future__ import annotations

import random
import threading
import time
from dataclasses import dataclass
from typing import Callable

# Messages and limits of the sketch. tests check these against the .ino so they can't drift.
MSG_READY = "# INA219 ready"
MSG_NOT_FOUND = "# INA219 not found: check SDA, SCL, VCC and GND"
MSG_READ_FAILED = "# INA219 read failed: check the wiring"
MSG_OVER_VOLTAGE = "# OVER 26 V: disconnect now, this exceeds the INA219's rating"
MSG_OVER_CURRENT = "# Current above the 3.2 A range: reading withheld"
LINE_WITH_TEMPERATURE = '{"voltage":%.3f,"current":%.4f,"temperature":%.2f}'           # firmware v1.0
LINE_WITHOUT_TEMPERATURE = '{"voltage":%.3f,"current":%.4f,"temperature":null}'        # firmware v1.0
# Firmware v1.1: the body (keys in the sketch's snprintf order) and the crc appended last.
LINE_V11_BODY = '{"voltage":%.3f,"current":%.4f,"temperature":%s,"ambient":%s,"seq":%d,"t_ms":%d'
LINE_V11_CRC = ',"crc":"%02X"}'
FW_VERSION = "1.1.0"
MSG_BOOT = "# boot reason=power_on"
MSG_FW = "# fw=revive_tery_esp32 v" + FW_VERSION + " profile=RANGE_32V_2A sensors=ina219,ds18b20"
MSG_DS18B20 = ("# ds18b20[0]=2800000000000001", "# ds18b20[1]=2800000000000002")   # simulated addresses
HEARTBEAT_S = 10.0
WARN_REPEAT_S = 10.0
SAMPLE_PERIOD_S = 1.0
SENSOR_RETRY_S = 5.0
INA219_MAX_BUS_VOLTAGE_V = 26.0
SHUNT_SATURATED_MV = 319.0
SHUNT_OHMS = 0.1

# Faults the dashboard can inject while a test runs.
FAULT_NONE = "none"
FAULT_INA219 = "ina219"
FAULT_DS18B20 = "ds18b20"
FAULT_OVER_VOLTAGE = "overvoltage"
FAULT_OVER_CURRENT = "overcurrent"
FAULT_SILENT = "silent"
FAULT_CRC = "crc_corruption"
FAULT_SEQ_GAP = "seq_gap"
FAULTS = {
    FAULT_NONE: "No fault",
    FAULT_INA219: "INA219 wire comes loose",
    FAULT_DS18B20: "DS18B20 temperature sensor disconnected",
    FAULT_OVER_VOLTAGE: "Over-voltage on the sensor inputs (+22 V)",
    FAULT_OVER_CURRENT: "Load draws 3.5 A (over the 3.2 A range)",
    FAULT_SILENT: "ESP32 stops sending (cable or board failure)",
    FAULT_CRC: "Lines corrupted on the cable (bad CRC)",
    FAULT_SEQ_GAP: "Lines lost on the way (seq gaps)",
}
OVER_VOLTAGE_OFFSET_V = 22.0
OVER_CURRENT_LOAD_A = 3.5

# The simulated cell: 1S Li-ion, open-circuit voltage against state of charge.
OCV_CURVE = ((0.0, 3.00), (10.0, 3.45), (50.0, 3.75), (90.0, 4.05), (100.0, 4.20))
CELL_RESISTANCE_OHM = 0.10
LOAD_CUTOFF_V = 3.00  # The test load switches off at this terminal voltage, as a real electronic load does.
# Thermal model: heat from I²R, shed to the room through a thermal resistance.
THERMAL_MASS_J_PER_K = 40.0
THERMAL_RESISTANCE_K_PER_W = 15.0
# INA219 with the 32 V / 2 A calibration: its resolution and typical noise.
BUS_VOLTAGE_LSB_V = 0.004
CURRENT_LSB_A = 0.0001
DS18B20_LSB_C = 0.0625
BUS_VOLTAGE_NOISE_V = 0.002
CURRENT_NOISE_A = 0.0005
TEMPERATURE_NOISE_C = 0.03
SILENT_TICK_LIMIT = 3600


def open_circuit_voltage(soc_pct: float) -> float:
    soc = max(0.0, min(100.0, soc_pct))
    for (x0, y0), (x1, y1) in zip(OCV_CURVE, OCV_CURVE[1:]):
        if soc <= x1:
            return y0 + (y1 - y0) * (soc - x0) / (x1 - x0)
    return OCV_CURVE[-1][1]


def _quantise(value: float, step: float) -> float:
    return round(value / step) * step


@dataclass(frozen=True)
class SimulationSettings:
    true_capacity_ah: float = 1.8
    start_soc_pct: float = 100.0
    load_current_a: float = 1.0
    speed: float = 60.0  # Simulated seconds per real second.
    seed: int | None = None


class SimulatedESP32:
    """Quacks like the pyserial port that bms_engine opens, but never accepts anything written to it."""

    def __init__(self, settings: SimulationSettings | None = None, start_epoch: float | None = None,
                 paced: bool = True, sleep: Callable[[float], None] = time.sleep,
                 wall: Callable[[], float] = time.monotonic):
        self.settings = settings or SimulationSettings()
        if self.settings.true_capacity_ah <= 0 or self.settings.load_current_a < 0 or self.settings.speed <= 0:
            raise ValueError("capacity and speed must be positive and the load can't be negative")
        self._start_epoch = time.time() if start_epoch is None else start_epoch
        self._paced = paced
        self._sleep = sleep
        self._wall = wall
        self._rng = random.Random(self.settings.seed)
        self._lock = threading.Lock()

        # What a pyserial port has. bms_engine sets these, then calls open().
        self.port = None
        self.baudrate = None
        self.timeout = 1.0
        self.dtr = None
        self.rts = None
        self.is_open = False

        self._fault = FAULT_NONE
        self._t = 0.0  # Simulated seconds since the start.
        self._queue: list[bytes] = []
        self._next_wall: float | None = None
        self._ready = True
        self._last_retry = 0.0
        self._seq = 0
        self._last_heartbeat = 0.0
        self._warn: dict[str, list[float]] = {}   # message -> [last print time, occurrences since], as the sketch

        # The battery and load.
        self.soc_pct = max(0.0, min(100.0, self.settings.start_soc_pct))
        self.delivered_ah = 0.0
        self.temperature_c = 25.0
        self.ambient_c = 25.0
        self.load_on = self.settings.load_current_a > 0
        self.complete = False  # True once the load has switched off at the cutoff voltage.
        self.terminal_v = open_circuit_voltage(self.soc_pct)
        self.current_a = 0.0

    # ---- what bms_engine uses

    def open(self) -> None:
        self.is_open = True
        self._next_wall = self._wall() + SAMPLE_PERIOD_S / self.settings.speed
        # setup() in the sketch announces the sensor, or reports it missing.
        for msg in (MSG_BOOT, MSG_FW):
            self._queue.append(msg.encode() + b"\r\n")
        if self._fault == FAULT_INA219:
            self._ready = False
            self._queue.append(MSG_NOT_FOUND.encode() + b"\r\n")
        else:
            self._queue.append(MSG_READY.encode() + b"\r\n")
        for msg in MSG_DS18B20:
            self._queue.append(msg.encode() + b"\r\n")

    def close(self) -> None:
        self.is_open = False

    def clock(self) -> float:
        """Time of the latest line, in simulated seconds from the start. Readings are stamped with
        this, so charge is counted over simulated time and not over the faster real time."""
        return self._start_epoch + self._t

    def readline(self) -> bytes:
        """Block until the next line is due, as a serial port does, or return b"" at the timeout."""
        deadline = self._wall() + (self.timeout or 1.0)
        silent_ticks = 0
        while True:
            if self._queue:
                return self._queue.pop(0)
            if not self.is_open:
                return b""
            if self._paced:
                remaining = deadline - self._wall()
                if remaining <= 0:
                    return b""
                wait = self._next_wall - self._wall()
                if wait > remaining:
                    self._sleep(remaining)
                    return b""
                if wait > 0:
                    self._sleep(wait)
                self._next_wall += SAMPLE_PERIOD_S / self.settings.speed
            elif silent_ticks >= SILENT_TICK_LIMIT:
                return b""
            lines = self._tick()
            silent_ticks = 0 if lines else silent_ticks + 1
            self._queue.extend(line.encode() + b"\r\n" for line in lines)

    # ---- fault injection

    def set_fault(self, fault: str) -> None:
        if fault not in FAULTS:
            raise ValueError(f"Unknown fault {fault!r}")
        with self._lock:
            self._fault = fault

    @property
    def fault(self) -> str:
        return self._fault

    # ---- the circuit

    def _load_current(self) -> float:
        if not self.load_on:
            return 0.0
        return OVER_CURRENT_LOAD_A if self._fault == FAULT_OVER_CURRENT else self.settings.load_current_a

    def _step_physics(self) -> None:
        dt = SAMPLE_PERIOD_S
        current = self._load_current()
        self.current_a = current
        self.delivered_ah += current * dt / 3600.0
        self.soc_pct = max(0.0, self.soc_pct - current * dt / 3600.0 / self.settings.true_capacity_ah * 100.0)
        self.terminal_v = open_circuit_voltage(self.soc_pct) - current * CELL_RESISTANCE_OHM
        heat_w = current * current * CELL_RESISTANCE_OHM
        loss_w = (self.temperature_c - self.ambient_c) / THERMAL_RESISTANCE_K_PER_W
        self.temperature_c += (heat_w - loss_w) * dt / THERMAL_MASS_J_PER_K

    def _throttle(self, msg: str) -> list[str]:
        """The sketch's flood control: a persisting warning at most every WARN_REPEAT_S, with "(x<n>)"."""
        st = self._warn.get(msg)
        if st is None:
            self._warn[msg] = [self._t, 0]
            return [msg]
        st[1] += 1
        if self._t - st[0] >= WARN_REPEAT_S:
            n = st[1]
            self._warn[msg] = [self._t, 0]
            return [f"{msg} (x{n})" if n > 1 else msg]
        return []

    def _clear_warn(self, *msgs: str) -> None:
        for m in msgs:
            self._warn.pop(m, None)

    def _tick(self) -> list[str]:
        lines = self._tick_inner()
        if self._fault != FAULT_SILENT and self._t - self._last_heartbeat >= HEARTBEAT_S:
            self._last_heartbeat = self._t
            lines.append(f"# hb seq={self._seq}")
        return lines

    def _line(self, voltage: float, current: float, temperature: float | None, ambient: float | None, fault: str) -> str:
        temp = "%.2f" % temperature if temperature is not None else "null"
        amb = "%.2f" % ambient if ambient is not None else "null"
        if fault == FAULT_SEQ_GAP:
            self._seq = (self._seq + 1) % (2 ** 32)   # one line "lost" before this one
        body = LINE_V11_BODY % (voltage, current, temp, amb, self._seq, int(round(self._t * 1000)))
        crc = _crc8(body.encode())
        if fault == FAULT_CRC:
            crc ^= 0x5A                                # corrupted on the cable: the receiver must reject it
        self._seq = (self._seq + 1) % (2 ** 32)
        return body + LINE_V11_CRC % crc

    def _tick_inner(self) -> list[str]:
        """One pass of the firmware's loop(), a second later. Returns the lines it would print."""
        with self._lock:
            fault = self._fault
        self._t += SAMPLE_PERIOD_S
        self._step_physics()
        sample_voltage = self.terminal_v
        sample_current = self.current_a
        if self.load_on and sample_voltage <= LOAD_CUTOFF_V:
            self.load_on = False  # Takes effect from the next sample, after this one is reported.
            self.complete = True
        if fault == FAULT_SILENT:
            return []

        if not self._ready:
            if self._t - self._last_retry >= SENSOR_RETRY_S:
                self._last_retry = self._t
                if fault == FAULT_INA219:
                    return self._throttle(MSG_NOT_FOUND)
                self._ready = True
                self._clear_warn(MSG_NOT_FOUND, MSG_READ_FAILED)
                return [MSG_READY]  # The sketch returns here, so there's no reading this cycle.
            return []
        if fault == FAULT_INA219:
            self._ready = False
            self._last_retry = self._t
            return self._throttle(MSG_READ_FAILED)

        # The INA219 measures the shunt drop, and the bus voltage on the load side of the shunt.
        shunt_mv = sample_current * SHUNT_OHMS * 1000.0
        bus_v = sample_voltage - shunt_mv / 1000.0
        if fault == FAULT_OVER_VOLTAGE:
            bus_v += OVER_VOLTAGE_OFFSET_V
        bus_v = _quantise(bus_v + self._rng.gauss(0, BUS_VOLTAGE_NOISE_V), BUS_VOLTAGE_LSB_V)
        current_a = _quantise(sample_current + self._rng.gauss(0, CURRENT_NOISE_A), CURRENT_LSB_A)
        shunt_mv = current_a * SHUNT_OHMS * 1000.0

        voltage = bus_v + shunt_mv / 1000.0  # As the sketch does, to get the battery's own voltage.
        if voltage > INA219_MAX_BUS_VOLTAGE_V:
            return self._throttle(MSG_OVER_VOLTAGE)
        self._clear_warn(MSG_OVER_VOLTAGE)
        if abs(current_a * 100.0) > SHUNT_SATURATED_MV:
            return self._throttle(MSG_OVER_CURRENT)
        self._clear_warn(MSG_OVER_CURRENT)

        temperature = None
        if fault != FAULT_DS18B20:
            temperature = _quantise(self.temperature_c + self._rng.gauss(0, TEMPERATURE_NOISE_C), DS18B20_LSB_C)
        ambient = _quantise(self.ambient_c + self._rng.gauss(0, TEMPERATURE_NOISE_C), DS18B20_LSB_C)
        return [self._line(voltage, current_a, temperature, ambient, fault)]


def _crc8(data: bytes) -> int:
    """CRC-8 of firmware v1.1 (polynomial 0x07, init 0x00, no reflection, no final xor)."""
    crc = 0
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = ((crc << 1) ^ 0x07) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
    return crc

