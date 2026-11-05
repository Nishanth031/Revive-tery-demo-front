"""Synthetic fault injection for validating detectors. Every function returns a NEW bundle."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

import numpy as np
import pandas as pd

from revive_ml.contract import Bundle
from revive_ml.synth import NMC_SPEC, PackSpec, make_clean_bundle


def _copy(b: Bundle) -> Bundle:
    return Bundle(meta=b.meta.model_copy(deep=True), telemetry=b.telemetry.copy(deep=True),
                  path=b.path, ignored_columns=list(b.ignored_columns))


def random_clean_bundle(seed: int) -> Bundle:
    """Clean synthetic bundle with randomised chemistry, sampling step and conditions."""
    rng = np.random.default_rng(10_000 + seed)
    base = PackSpec() if rng.random() < 0.5 else NMC_SPEC
    spec = replace(base, soh=float(rng.uniform(0.75, 0.98)))
    return make_clean_bundle(spec, seed=seed, dt_s=float(rng.choice([1.0, 5.0, 10.0, 30.0])),
                             soc0=float(rng.uniform(0.6, 0.9)),
                             ambient_c=float(rng.uniform(10, 35)))


def _active_rows(b: Bundle) -> np.ndarray:
    i = b.telemetry["current_a"].to_numpy(float)
    return np.flatnonzero(np.abs(i) > 0.05 * b.meta.rated_capacity_ah)


def flip_sign_keep_declaration(b: Bundle, rng: np.random.Generator) -> Bundle:
    out = _copy(b)
    out.telemetry["current_a"] *= -1
    return out


def scale_current(b: Bundle, rng: np.random.Generator) -> Bundle:
    out = _copy(b)
    out.telemetry["current_a"] *= rng.uniform(0.4, 0.7)  # current explains too little SOC change
    return out


def regen_wrong_sign(b: Bundle, rng: np.random.Generator) -> Bundle:
    out = _copy(b)
    df = out.telemetry
    m = df["operating_state"].isin(["REGENERATIVE_BRAKING", "CHARGING"])
    df.loc[m, "current_a"] = -df.loc[m, "current_a"].abs()
    return out


def implausible_resistance(b: Bundle, rng: np.random.Generator) -> Bundle:
    out = _copy(b)
    f = rng.uniform(0.01, 0.08)  # clearly below the 10 mOhm*Ah floor for both test packs
    out.meta.resistance_tests = [t.model_copy(update={"resistance_mohm": t.resistance_mohm * f})
                                 for t in out.meta.resistance_tests]
    return out


def duplicate_timestamps(b: Bundle, rng: np.random.Generator) -> Bundle:
    out = _copy(b)
    df = out.telemetry
    idx = rng.choice(len(df), size=max(2, len(df) // 100), replace=False)
    out.telemetry = pd.concat([df, df.iloc[idx]]).sort_values("timestamp_utc", kind="stable") \
        .reset_index(drop=True)
    return out


def reverse_time(b: Bundle, rng: np.random.Generator) -> Bundle:
    out = _copy(b)
    df = out.telemetry
    k = int(rng.integers(5, len(df) - 5))
    ts = df["timestamp_utc"].copy()
    ts.iloc[k], ts.iloc[k + 1] = ts.iloc[k + 1], ts.iloc[k]
    df["timestamp_utc"] = ts
    return out


def large_gap(b: Bundle, rng: np.random.Generator) -> Bundle:
    out = _copy(b)
    n = len(out.telemetry)
    start = int(rng.integers(n // 10, n // 2))
    width = int(n * rng.uniform(0.25, 0.4))
    out.telemetry = out.telemetry.drop(index=range(start, start + width)).reset_index(drop=True)
    return out


def irregular_steps(b: Bundle, rng: np.random.Generator) -> Bundle:
    out = _copy(b)
    df = out.telemetry
    step = (df["timestamp_utc"].iloc[1] - df["timestamp_utc"].iloc[0]).total_seconds()
    jitter = rng.uniform(0.3, 0.45) * step * rng.choice([-1, 1], size=len(df))
    jitter[0] = 0
    df["timestamp_utc"] = df["timestamp_utc"] + pd.to_timedelta(jitter, unit="s")
    return out


def null_voltage(b: Bundle, rng: np.random.Generator) -> Bundle:
    out = _copy(b)
    df = out.telemetry
    idx = rng.choice(len(df), size=int(len(df) * rng.uniform(0.12, 0.3)), replace=False)
    df.loc[idx, "voltage_v"] = np.nan
    return out


def voltage_dropout(b: Bundle, rng: np.random.Generator) -> Bundle:
    out = _copy(b)
    df = out.telemetry
    k = int(rng.integers(10, len(df) - 10))
    df.loc[k:k + int(rng.integers(1, 4)), "voltage_v"] = 0.0
    return out


def stuck_voltage(b: Bundle, rng: np.random.Generator) -> Bundle:
    out = _copy(b)
    df = out.telemetry
    act = _active_rows(b)
    k = int(rng.choice(act[: len(act) // 2]))
    run = int(rng.integers(12, 40))
    df.loc[k:k + run, "voltage_v"] = df.loc[k, "voltage_v"]
    return out


def temperature_spike(b: Bundle, rng: np.random.Generator) -> Bundle:
    out = _copy(b)
    df = out.telemetry
    k = int(rng.integers(20, len(df) - 20))
    df.loc[k, "temperature_c"] += rng.uniform(12, 30) * rng.choice([-1, 1])
    return out


def out_of_range_temperature(b: Bundle, rng: np.random.Generator) -> Bundle:
    out = _copy(b)
    df = out.telemetry
    k = int(rng.integers(0, len(df)))
    df.loc[k, "temperature_c"] = rng.uniform(150, 250)
    return out


def temperature_missing(b: Bundle, rng: np.random.Generator) -> Bundle:
    out = _copy(b)
    out.telemetry["temperature_c"] = np.nan
    return out


def capacity_test_disagrees(b: Bundle, rng: np.random.Generator) -> Bundle:
    out = _copy(b)
    tests = out.meta.capacity_tests
    soh_true = tests[-1].measured_capacity_ah / out.meta.rated_capacity_ah
    target = soh_true + rng.choice([-1, 1]) * rng.uniform(0.25, 0.4)
    target = float(np.clip(target, 0.3, 1.2))
    # the live SOC trace stays consistent with the true capacity; only the test record is wrong
    tests[-1] = tests[-1].model_copy(update={"measured_capacity_ah": target * out.meta.rated_capacity_ah})
    return out


def mislabelled_measured(b: Bundle, rng: np.random.Generator) -> Bundle:
    out = _copy(b)
    out.meta.data_provenance = "measured"
    return out


# fault name -> (injector, detector id, statuses counted as a detection)
FAULTS: dict[str, tuple[Callable[[Bundle, np.random.Generator], Bundle], str, tuple[str, ...]]] = {
    "sign_flip_vs_declared": (flip_sign_keep_declaration, "sign_convention", ("fail",)),
    "charge_balance_mismatch": (scale_current, "charge_balance", ("fail", "warn")),
    "regen_wrong_sign": (regen_wrong_sign, "regen_sign", ("fail", "warn")),
    "implausible_resistance": (implausible_resistance, "resistance", ("inconclusive",)),
    "duplicate_timestamps": (duplicate_timestamps, "timestamps", ("fail",)),
    "non_monotonic_time": (reverse_time, "timestamps", ("fail",)),
    "large_gap": (large_gap, "timestamps", ("fail", "warn")),
    "irregular_steps": (irregular_steps, "timestamps", ("warn", "fail")),
    "null_voltage": (null_voltage, "sensor_nulls", ("fail", "warn")),
    "voltage_dropout": (voltage_dropout, "sensor_dropouts", ("fail", "warn")),
    "stuck_voltage": (stuck_voltage, "sensor_stuck", ("fail",)),
    "temperature_spike": (temperature_spike, "sensor_spikes", ("fail", "warn")),
    "out_of_range_temperature": (out_of_range_temperature, "sensor_range", ("fail",)),
    "temperature_missing": (temperature_missing, "temperature_missing", ("fail",)),
    "capacity_test_disagrees": (capacity_test_disagrees, "estimate_disagreement", ("fail", "warn")),
    "mislabelled_measured": (mislabelled_measured, "provenance", ("fail",)),
}
