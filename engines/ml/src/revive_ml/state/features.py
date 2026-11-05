"""Sliding-window diagnostic features.

A used battery is observed over its most recent WINDOW cycles ending at cycle k. Features
describe that window; targets are the SOH at k and the remaining cycles to EOL (80 % of
nominal). Windows of one cell must never cross a train/test split (see train.py).

Two feature sets:
  FIELD  only what a used-battery bundle can provide (capacity tests, resistance tests,
         temperatures, cycle count). Used for real assessments.
  FULL   FIELD plus per-cycle curve features that need lab cycling data (Var of dQ(V)
         between the window ends, as in Severson et al. 2019, and charge time).
SOH_FEATURES excludes every capacity-derived feature so the SOH model is a genuine cross-check.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from revive_ml.paths import PROCESSED_DIR

WINDOW = 50
STEP = 10
MIN_START = 20  # skip formation cycles
NOMINAL_AH = 1.1

FIELD = ["soh", "fade_slope_per_kcycle", "fade_accel_per_kcycle", "ir_ratio", "t_mean_c", "t_max_c",
         "cycles_so_far"]
FULL = [*FIELD, "log_var_dq", "log_abs_min_dq", "chargetime_min"]
SOH_FEATURES = ["ir_ratio", "t_mean_c", "t_max_c", "cycles_so_far", "log_var_dq", "log_abs_min_dq",
                "chargetime_min"]


def _slope(x: np.ndarray, y: np.ndarray) -> float:
    m = np.isfinite(x) & np.isfinite(y)
    if m.sum() < 3 or np.ptp(x[m]) == 0:
        return 0.0
    return float(np.polyfit(x[m], y[m], 1)[0])


def window_row(cycles: np.ndarray, soh: np.ndarray, ir: np.ndarray | None, ir_first: float | None,
               t_mean: np.ndarray | None, t_max: np.ndarray | None, k_cycles: float) -> dict[str, float]:
    """Field features from (possibly sparse) records inside one window. Shared by ETL and bundles."""
    half = cycles.min() + (cycles.max() - cycles.min()) / 2
    first, second = cycles <= half, cycles >= half
    s_all = _slope(cycles, soh)
    accel = _slope(cycles[second], soh[second]) - _slope(cycles[first], soh[first]) \
        if first.sum() >= 2 and second.sum() >= 2 else 0.0
    ir_now = float(np.nanmedian(ir[-5:])) if ir is not None and np.isfinite(ir).any() else np.nan
    return {
        "soh": float(np.nanmedian(soh[-5:])),
        "fade_slope_per_kcycle": -1000.0 * s_all,
        "fade_accel_per_kcycle": -1000.0 * accel,
        "ir_ratio": ir_now / ir_first if ir_first and np.isfinite(ir_now) else np.nan,
        "t_mean_c": float(np.nanmean(t_mean)) if t_mean is not None else np.nan,
        "t_max_c": float(np.nanmax(t_max)) if t_max is not None else np.nan,
        "cycles_so_far": float(k_cycles),
    }


def severson_windows(window: int = WINDOW, step: int = STEP) -> pd.DataFrame:
    cells = pd.read_parquet(PROCESSED_DIR / "severson_cells.parquet")
    cells = cells[cells.excluded.isna()]
    summ = pd.read_parquet(PROCESSED_DIR / "severson_summary.parquet")
    qd = pd.read_parquet(PROCESSED_DIR / "severson_qdlin.parquet")
    rows = []
    for cell in cells.itertuples():
        s = summ[summ.cell == cell.cell].sort_values("cycle")
        s = s[s.cycle >= 1]
        q = qd[qd.cell == cell.cell].set_index("cycle")["qdlin"]
        qcycles = q.index.to_numpy()
        cyc = s.cycle.to_numpy(float)
        soh = s.qd.rolling(5, min_periods=1).median().to_numpy() / NOMINAL_AH
        ir = s.ir.replace(0, np.nan).to_numpy()
        ir_first = float(np.nanmedian(ir[(cyc >= 2) & (cyc <= 11)]))
        eol = cell.eol_cycle
        for k in range(MIN_START + window, int(eol), step):
            m = (cyc > k - window) & (cyc <= k)
            if m.sum() < window // 2:
                continue
            r = window_row(cyc[m], soh[m], ir[m], ir_first, s.tavg.to_numpy()[m], s.tmax.to_numpy()[m], k)
            # curve features: nearest stored Qdlin to k and to k - window (within 5 cycles)
            ia, ib = np.abs(qcycles - k).argmin(), np.abs(qcycles - (k - window)).argmin()
            if abs(qcycles[ia] - k) <= 5 and abs(qcycles[ib] - (k - window)) <= 5 and ia != ib:
                dq = np.asarray(q.iloc[ia], float) - np.asarray(q.iloc[ib], float)
                r["log_var_dq"] = float(np.log10(np.var(dq) + 1e-12))
                r["log_abs_min_dq"] = float(np.log10(np.abs(dq.min()) + 1e-12))
            else:
                r["log_var_dq"] = r["log_abs_min_dq"] = np.nan
            r["chargetime_min"] = float(np.nanmean(s.chargetime.to_numpy()[m]))
            r.update({"cell": cell.cell, "batch": cell.batch, "policy": cell.policy, "eol_cycle": eol,
                      "rul_cycles": float(eol - k), "soh_target": r["soh"]})
            rows.append(r)
    out = pd.DataFrame(rows)
    out.to_parquet(PROCESSED_DIR / "severson_windows.parquet", index=False)
    return out
