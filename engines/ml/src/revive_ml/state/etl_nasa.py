"""ETL for the NASA PCoE Battery Data Set (#5): MATLAB v5 files -> parquet.

Outputs (data/processed/):
  nasa_cycles.parquet      one row per discharge cycle: capacity, ambient, impedance (Re, Rct)
  nasa_timeseries.parquet  discharge time series (and every 10th charge) for gate training
Source current is discharge-negative (Current_measured < 0 on discharge).
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import scipy.io as sio

from revive_ml.paths import PROCESSED_DIR, cache_dir
from revive_ml.state.download import local_path

RATED_AH = 2.0  # per the NASA README (2 Ah 18650 cells)


def extract(force: bool = False) -> Path:
    raw = local_path("nasa_pcoe_battery")
    if raw is None:
        raise FileNotFoundError("NASA zip not downloaded; run `revive-ml download nasa_pcoe_battery`")
    out = cache_dir() / "extracted" / "nasa" / "mats"
    if out.exists() and any(out.glob("B*.mat")) and not force:
        return out
    out.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(raw) as outer:
        for name in outer.namelist():
            if name.endswith(".zip"):
                with outer.open(name) as fh, zipfile.ZipFile(fh) as inner:
                    for member in inner.namelist():
                        target = (out / Path(member).name).resolve()
                        if target.parent != out.resolve() or not member.lower().endswith((".mat", ".txt")):
                            continue  # ignore anything that is not a flat data/readme file
                        target.write_bytes(inner.read(member))
    return out


def _arr(x: object) -> np.ndarray:
    a = np.asarray(x).ravel()
    return (np.abs(a) if np.iscomplexobj(a) else a).astype(float)


def run(charge_every: int = 10) -> dict[str, int]:
    mats = extract()
    cycles, series = [], []
    for f in sorted(mats.glob("B*.mat")):
        cell = f.stem
        m = sio.loadmat(f, simplify_cells=True)
        cyc = m[cell]["cycle"]
        last_re = last_rct = np.nan
        n_dis = n_chg = 0
        for k, c in enumerate(cyc):
            d = c["data"]
            amb = float(c["ambient_temperature"])
            if c["type"] == "impedance":
                re, rct = _arr(d.get("Re", np.nan)), _arr(d.get("Rct", np.nan))
                last_re = float(np.abs(re[0])) if re.size else np.nan
                last_rct = float(np.abs(rct[0])) if rct.size else np.nan
                continue
            t = _arr(d["Time"])
            if t.size < 5:
                continue
            frame = pd.DataFrame({"cell": cell, "op_index": k, "type": c["type"], "ambient_c": amb,
                                  "time_s": t, "voltage_v": _arr(d["Voltage_measured"]),
                                  "current_a": _arr(d["Current_measured"]),
                                  "temperature_c": _arr(d["Temperature_measured"])})
            if c["type"] == "discharge":
                cap = _arr(d.get("Capacity", np.nan))
                cycles.append({"cell": cell, "discharge_index": n_dis, "op_index": k, "ambient_c": amb,
                               "capacity_ah": float(cap[0]) if cap.size else np.nan,
                               "re_ohm": last_re, "rct_ohm": last_rct,
                               "t_mean_c": float(frame.temperature_c.mean()),
                               "t_max_c": float(frame.temperature_c.max()),
                               "duration_s": float(t[-1] - t[0])})
                frame["discharge_index"] = n_dis
                n_dis += 1
                series.append(frame)
            elif c["type"] == "charge":
                if n_chg % charge_every == 0:
                    frame["discharge_index"] = n_dis
                    series.append(frame)
                n_chg += 1
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    cyc_df = pd.DataFrame(cycles)
    cyc_df["soh"] = cyc_df["capacity_ah"] / RATED_AH
    cyc_df.to_parquet(PROCESSED_DIR / "nasa_cycles.parquet", index=False)
    ts = pd.concat(series, ignore_index=True)
    ts.to_parquet(PROCESSED_DIR / "nasa_timeseries.parquet", index=False)
    return {"cells": int(cyc_df.cell.nunique()), "discharge_cycles": len(cyc_df), "series_rows": len(ts)}
