"""Physically consistent SYNTHETIC pack telemetry.

Used for (a) the clean example bundle that exercises the full pipeline and (b) fault
injection. Every bundle produced here has data_provenance="synthetic". Nothing here is
a measurement and nothing here is used to train the state model.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
import pandas as pd

from revive_ml.contract import Bundle, CapacityTest, Metadata, ResistanceTest, validate_telemetry


def ocv_cell(soc: np.ndarray, chemistry: str) -> np.ndarray:
    """Smooth illustrative open-circuit-voltage curves (not fitted to any datasheet)."""
    s = np.clip(soc, 0.0, 1.0)
    if chemistry == "LFP":
        return 3.26 + 0.10 * (s - 0.5) - 0.30 * np.exp(-s / 0.05) + 0.15 * np.exp((s - 1) / 0.03)
    return 3.45 + 0.75 * s - 0.30 * np.exp(-s / 0.08)  # NMC / NCA


@dataclass(frozen=True)
class PackSpec:
    chemistry: str = "LFP"
    series: int = 96
    parallel: int = 1
    cell_capacity_ah: float = 100.0
    cell_r_mohm: float = 0.8
    v_min_cell: float = 2.5
    v_nom_cell: float = 3.2
    v_max_cell: float = 3.65
    soh: float = 0.92


NMC_SPEC = PackSpec(chemistry="NMC", series=96, parallel=40, cell_capacity_ah=5.0,
                    cell_r_mohm=20.0, v_min_cell=3.0, v_nom_cell=3.7, v_max_cell=4.2, soh=0.92)


def current_profile(n: int, dt_s: float, capacity_ah: float, rng: np.random.Generator) -> np.ndarray:
    """Rest, drive (discharge with regen bursts), rest, CC charge, rest. Charge is positive."""
    t = np.arange(n) * dt_s
    i = np.zeros(n)
    drive = (t >= 600) & (t < 4200)
    base = -0.35 * capacity_ah * (1 + 0.6 * np.sin(t / 97.0) + 0.3 * np.sin(t / 23.0))
    i[drive] = base[drive] + rng.normal(0, 0.03 * capacity_ah, drive.sum())
    regen = drive & (np.sin(t / 61.0) > 0.85)
    i[regen] = 0.15 * capacity_ah
    charge = (t >= 5400) & (t < 9000)
    i[charge] = 0.5 * capacity_ah
    return i


DEFAULT_SPEC = PackSpec()


def make_clean_bundle(spec: PackSpec = DEFAULT_SPEC, seed: int = 0, duration_s: int = 10_200,
                      dt_s: float = 10.0, asset_id: str = "SYNTH-CLEAN-001",
                      soc0: float = 0.8, ambient_c: float = 25.0) -> Bundle:
    rng = np.random.default_rng(seed)
    n = int(duration_s / dt_s)
    pack_cap = spec.cell_capacity_ah * spec.parallel
    true_cap = pack_cap * spec.soh
    i = current_profile(n, dt_s, pack_cap, rng)
    soc = np.empty(n)
    soc[0] = soc0
    for k in range(1, n):
        if soc[k - 1] >= 0.95 and i[k] > 0:
            i[k] = 0.0  # charger stops at 95 % SOC
        soc[k] = soc[k - 1] + 0.5 * (i[k] + i[k - 1]) * dt_s / 3600 / true_cap
    r_pack = spec.cell_r_mohm * 1e-3 * spec.series / spec.parallel / (0.5 + 0.5 * spec.soh)
    v = spec.series * ocv_cell(soc, spec.chemistry) + i * r_pack
    temp = np.empty(n)
    temp[0] = ambient_c + 1.0
    heat_cap, h = 60_000.0 * (pack_cap / 100), 25.0  # J/K, W/K (illustrative)
    for k in range(1, n):
        q = i[k] ** 2 * r_pack - h * (temp[k - 1] - ambient_c)
        temp[k] = temp[k - 1] + q * dt_s / heat_cap
    v += rng.normal(0, 0.02 * spec.series / 96, n)
    temp += rng.normal(0, 0.05, n)
    ts = pd.Timestamp("2026-10-20T08:00:00Z") + pd.to_timedelta(np.arange(n) * dt_s, unit="s")
    state = np.where(i < -1e-9, "DRIVING", np.where(i > 1e-9, "CHARGING", "IDLE"))
    drive_window = (np.arange(n) * dt_s >= 600) & (np.arange(n) * dt_s < 4200)
    state = np.where(drive_window & (i > 0), "REGENERATIVE_BRAKING", state)
    df = pd.DataFrame({
        "asset_id": asset_id,
        "timestamp_utc": ts,
        "voltage_v": v.round(3),
        "current_a": i.round(3),
        "temperature_c": temp.round(2),
        "soc_pct": (soc * 100).round(2),
        "ambient_temperature_c": ambient_c,
        "power_kw": (v * i / 1000).round(4),  # same sign convention as current
        "operating_state": state,
    })
    cycles = [100, 300, 500, 700, 900]
    soh_hist = np.interp(cycles, [0, 900], [1.0, spec.soh])
    tests = [
        CapacityTest(date=date(2024, 6, 30) + timedelta(days=180 * j), cycle_count=c,
                     measured_capacity_ah=round(pack_cap * s, 2), method="synthetic full-cycle test",
                     provenance="synthetic")
        for j, (c, s) in enumerate(zip(cycles, soh_hist, strict=True))
    ]
    r_tests = [
        ResistanceTest(date=t.date, cycle_count=t.cycle_count, level="pack", method="synthetic DCIR",
                       resistance_mohm=round(r_pack * 1e3 * (0.5 + 0.5 * spec.soh) / (0.5 + 0.5 * s), 2),
                       provenance="synthetic")
        for t, s in zip(tests, soh_hist, strict=True)
    ]
    meta = Metadata(
        asset_id=asset_id, chemistry=spec.chemistry, rated_capacity_ah=pack_cap,
        nominal_voltage_v=spec.series * spec.v_nom_cell, min_voltage_v=spec.series * spec.v_min_cell,
        max_voltage_v=spec.series * spec.v_max_cell, series_cells=spec.series,
        parallel_cells=spec.parallel, data_provenance="synthetic",
        current_sign_convention="discharge_negative", cycle_count=cycles[-1],
        capacity_tests=tests, resistance_tests=r_tests,
        notes="SYNTHETIC clean example generated by revive_ml.synth; not a real battery.",
        source=f"revive_ml.synth.make_clean_bundle(seed={seed})",
    )
    df, _ = validate_telemetry(df, asset_id)
    return Bundle(meta=meta, telemetry=df)
