"""REVIVE-TERY test bench: the digital twin's data feed and the end-of-life decision rules.

VirtualBattery replays recorded telemetry from DuckDB when no hardware is plugged in. It
replays what was recorded and never invents readings, so a short recording gives a short
test. get_secondary_use_case holds the decision rules.
"""
from __future__ import annotations

import math
import threading
from pathlib import Path
from typing import Iterator

import duckdb

from bms_engine import KEY_COLUMN, TIME_COLUMN, BMSEngine, DatabaseUnavailable, Sample, open_db, table_columns

# The demo bundle records discharge as negative current: SOC falls while current is below
# zero. BMSEngine needs to know this, because the SOC formula assumes the opposite.
BUNDLE_DISCHARGE_POSITIVE = False

# Columns a replay can't work without.
REQUIRED_COLUMNS = {KEY_COLUMN, TIME_COLUMN, "pack_voltage_v", "pack_current_a"}
BATCH_SIZE = 500

# Secondary use tiers. Each entry is (SOH must be above this, use case).
TIER_STATIONARY = "Stationary Storage"
TIER_LOW_SPEED_EV = "Low-speed EVs"
TIER_RECYCLING = "Recycling"
INSUFFICIENT_DATA = "Insufficient data"
STATIONARY_ABOVE_PCT = 80.0
LOW_SPEED_FROM_PCT = 60.0

SCREENING_NOTE = (
    "This is a screening rule based on capacity alone. Real reuse needs safety, "
    "resistance and cell-level testing by a qualified engineer."
)


class VirtualBattery:
    """Replay a battery's recorded telemetry row by row, with a short delay between rows.

    Iterating yields the same Sample type the ESP32 reader does, so the BMS engine can't tell
    the difference. Samples keep their recorded timestamps, so charge is counted over the
    time that really passed between rows and not over the replay delay.
    """

    def __init__(self, asset_id: str, delay_s: float = 1.0, stop_event: threading.Event | None = None,
                 path: Path | None = None, batch_size: int = BATCH_SIZE):
        self.asset_id = asset_id
        self.delay_s = delay_s
        self.stop_event = stop_event or threading.Event()
        self.path = path
        self.batch_size = batch_size

    def _read_batch(self, offset: int) -> list[Sample]:
        """Read one batch, closing the connection before the delay so the logger can write."""
        try:
            with open_db(path=self.path) as con:
                columns = table_columns(con, "telemetry")
                missing = REQUIRED_COLUMNS - columns
                if missing:
                    raise DatabaseUnavailable(f"The telemetry table is missing: {', '.join(sorted(missing))}")
                # Epoch milliseconds avoids the optional pytz package that time zone values need.
                optional = [
                    f'"{name}"' if name in columns else "NULL"
                    for name in ("max_cell_temp_c", "soc_pct", "operating_state")
                ]
                rows = con.execute(
                    f"""SELECT epoch_ms(CAST("{TIME_COLUMN}" AS TIMESTAMPTZ)), "pack_voltage_V", "pack_current_A",
                               {', '.join(optional)}
                        FROM telemetry WHERE "{KEY_COLUMN}" = ?
                        ORDER BY "{TIME_COLUMN}" LIMIT ? OFFSET ?""",
                    [self.asset_id, self.batch_size, offset],
                ).fetchall()
        except duckdb.Error as exc:
            raise DatabaseUnavailable(f"Could not read telemetry for {self.asset_id}: {exc}") from exc
        return [
            Sample(
                timestamp=stamp / 1000.0,
                voltage_v=float(voltage),
                current_a=float(current),
                temperature_c=float(temperature) if temperature is not None else None,
                reported_soc_pct=float(soc) if soc is not None else None,
                state=str(state or ""),
            )
            for stamp, voltage, current, temperature, soc, state in rows
            if stamp is not None and voltage is not None and current is not None
        ]

    def __iter__(self) -> Iterator[Sample]:
        offset = 0
        while not self.stop_event.is_set():
            batch = self._read_batch(offset)
            if not batch:
                return
            for sample in batch:
                if self.stop_event.is_set():
                    return
                yield sample
                # Waits on the event rather than sleeping, so Stop takes effect immediately.
                self.stop_event.wait(self.delay_s)
            if len(batch) < self.batch_size:
                return
            offset += self.batch_size


def get_secondary_use_case(soh_percentage: float | None) -> str:
    """Return the secondary use tier for a State of Health.

    Above 80% is Stationary Storage, 60% to 80% inclusive is Low-speed EVs, and below 60%
    is Recycling. A missing or invalid SOH gives "Insufficient data", because a battery
    shouldn't be sent to recycling or reuse on no evidence.
    """
    if soh_percentage is None or isinstance(soh_percentage, bool):
        return INSUFFICIENT_DATA
    try:
        soh = float(soh_percentage)
    except (TypeError, ValueError):
        return INSUFFICIENT_DATA
    if not math.isfinite(soh) or soh < 0:
        return INSUFFICIENT_DATA
    if soh > STATIONARY_ABOVE_PCT:
        return TIER_STATIONARY
    if soh >= LOW_SPEED_FROM_PCT:
        return TIER_LOW_SPEED_EV
    return TIER_RECYCLING


def get_decision_for_ui(engine: BMSEngine) -> dict:
    """The final decision to hand to the Circuit Studio, based on the engine's best SOH.

    use_case is the plain string to display. The other keys say what it rests on, so the
    dashboard can show the evidence next to the verdict.
    """
    soh, basis = engine.final_soh()
    return {
        "use_case": get_secondary_use_case(soh),
        "soh_pct": soh,
        "basis": basis,
        "live_soh_pct": engine.soh_live_pct,
        "live_basis": engine.soh_basis,
        "flags": engine.data_flags(),
        "note": SCREENING_NOTE,
    }
