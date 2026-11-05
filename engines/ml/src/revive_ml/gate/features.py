"""Window features for the out-of-distribution / sensor-noise filter.

All features are per cell and per unit capacity so that packs and single cells share one
feature space. Windows are fixed row counts; derivatives use the actual row-to-row step.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

WINDOW = 20
STRIDE = 10
MIN_ROWS = 8
FEATURES = [
    "v_level",         # mean cell voltage, normalised to the chemistry window [v_min, v_max]
    "c_rate_rms",      # RMS current / capacity
    "resid_mad_mv",    # robust noise of dV after explaining it by charge moved and ohmic steps
    "resid_max_z",     # largest residual in robust z units (spikes, dropouts)
    "resid_mean_t",    # t-statistic of the mean residual (slow drift)
    "temp_slope_c_per_min",  # least-squares temperature trend
    "temp_resid_z",      # largest deviation of temperature from its trend, robust z units
    "v_repeat_frac",   # share of exactly repeated voltage readings
]


def window_features(cell_v: np.ndarray, c_rate: np.ndarray, temp: np.ndarray, t_s: np.ndarray,
                    v_min: float, v_max: float, window: int = WINDOW, stride: int = STRIDE) -> pd.DataFrame:
    """c_rate must be charge-positive. Returns one row per window."""
    n = len(cell_v)
    if n < MIN_ROWS:
        return pd.DataFrame(columns=FEATURES)
    w = min(window, n)
    rows = []
    for s in range(0, n - w + 1, stride if n > w else 1):
        e = s + w
        v, c, T, t = cell_v[s:e], c_rate[s:e], temp[s:e], t_s[s:e]
        dt = np.diff(t)
        dt = np.where(dt > 0, dt, np.nan)
        dv = np.diff(v)
        X = np.column_stack([0.5 * (c[1:] + c[:-1]) * dt / 3600.0, np.diff(c)])
        ok = np.isfinite(dv) & np.isfinite(X).all(axis=1)
        if ok.sum() >= 4:
            coef, *_ = np.linalg.lstsq(X[ok], dv[ok], rcond=None)
            resid = dv[ok] - X[ok] @ coef
        else:
            resid = np.nan_to_num(dv[np.isfinite(dv)])
        mad = 1.4826 * np.median(np.abs(resid - np.median(resid))) if resid.size else 0.0
        scale = mad + 1e-4  # 0.1 mV floor
        tm = (t - t[0]) / 60.0
        okT = np.isfinite(T) & np.isfinite(tm)
        if okT.sum() >= 3 and np.ptp(tm[okT]) > 0:
            pT = np.polyfit(tm[okT], T[okT], 1)
            rT = T[okT] - np.polyval(pT, tm[okT])
            madT = 1.4826 * np.median(np.abs(rT - np.median(rT)))
            temp_slope, temp_z = float(pT[0]), float(np.max(np.abs(rT)) / (madT + 0.1))
        else:
            temp_slope, temp_z = 0.0, 0.0
        rows.append({
            "v_level": float((np.nanmean(v) - v_min) / (v_max - v_min)),
            "c_rate_rms": float(np.sqrt(np.nanmean(c ** 2))),
            "resid_mad_mv": float(1e3 * mad),
            "resid_max_z": float(np.max(np.abs(resid)) / scale) if resid.size else 0.0,
            "resid_mean_t": float(np.mean(resid) / (np.std(resid) / np.sqrt(resid.size) + 1e-4))
            if resid.size > 2 else 0.0,
            "temp_slope_c_per_min": temp_slope,
            "temp_resid_z": temp_z,
            "v_repeat_frac": float(np.mean(dv == 0)),
        })
    out = pd.DataFrame(rows, columns=FEATURES)
    return out.replace([np.inf, -np.inf], np.nan).fillna(0.0)
