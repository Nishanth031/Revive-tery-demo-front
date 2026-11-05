"""Train and validate the OOD filter on healthy windows; write reports/gate_validation.json.

Healthy windows come from two sources, kept separate in every reported rate:
  nasa       MEASURED: NASA PCoE cells B0005-7, B0018, B0025-32 (24 and 43 degC), cycles whose
             discharge capacity is >= 1.6 Ah (80 % of the 2 Ah rating). Voltage window 2.5-4.2 V
             (assumed; cathode chemistry is not stated in the source README).
  synthetic  SYNTHETIC: clean packs from revive_ml.synth (LFP and NMC, randomised conditions).
Groups (cells / synthetic seeds) never cross the train/test split.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from revive_ml.dq.detectors import seconds
from revive_ml.dq.inject import random_clean_bundle
from revive_ml.gate.features import window_features
from revive_ml.gate.ood import OODFilter, chemistry_window
from revive_ml.paths import PROCESSED_DIR, REPORTS_DIR

HEALTHY_NASA = ["B0005", "B0006", "B0007", "B0018", "B0025", "B0026", "B0027", "B0028",
                "B0029", "B0030", "B0031", "B0032"]
NASA_RATED_AH, NASA_V = 2.0, (2.5, 4.2)
SEED = 0


@dataclass
class Segment:
    source: str
    group: str
    v: np.ndarray       # cell voltage
    c: np.ndarray       # charge-positive C-rate
    T: np.ndarray
    t: np.ndarray
    vmin: float
    vmax: float

    def features(self) -> pd.DataFrame:
        return window_features(self.v, self.c, self.T, self.t, self.vmin, self.vmax)


def nasa_segments(max_per_cell: int = 60) -> list[Segment]:
    cyc = pd.read_parquet(PROCESSED_DIR / "nasa_cycles.parquet")
    ts = pd.read_parquet(PROCESSED_DIR / "nasa_timeseries.parquet")
    ok = cyc[cyc.cell.isin(HEALTHY_NASA) & (cyc.capacity_ah >= 0.8 * NASA_RATED_AH)]
    keep = set(zip(ok.cell, ok.discharge_index, strict=True))
    segs = []
    rng = np.random.default_rng(SEED)
    for (cell, _op), g in ts[ts.cell.isin(HEALTHY_NASA)].groupby(["cell", "op_index"], sort=True):
        if (cell, int(g.discharge_index.iloc[0])) not in keep or len(g) < 20:
            continue
        segs.append(Segment("nasa", cell, g.voltage_v.to_numpy(), g.current_a.to_numpy() / NASA_RATED_AH,
                            g.temperature_c.to_numpy(), g.time_s.to_numpy(), *NASA_V))
    by_cell: dict[str, list[Segment]] = {}
    for s in segs:
        by_cell.setdefault(s.group, []).append(s)
    out = []
    for cell_segs in by_cell.values():
        idx = rng.permutation(len(cell_segs))[:max_per_cell]
        out.extend(cell_segs[i] for i in sorted(idx))
    return out


def synthetic_segments(n: int = 150) -> list[Segment]:
    segs = []
    for s in range(n):
        b = random_clean_bundle(5000 + s)
        df, m = b.telemetry, b.meta
        vmin, vmax = chemistry_window(m.chemistry)
        segs.append(Segment("synthetic", f"synth-{s}", df.voltage_v.to_numpy() / m.series_cells,
                            df.current_a.to_numpy() / m.rated_capacity_ah, df.temperature_c.to_numpy(),
                            seconds(df.timestamp_utc), vmin, vmax))
    return segs


# ------------------------------------------------------------------ injected sensor faults
def _spike(s: Segment, rng: np.random.Generator) -> Segment:
    v = s.v.copy()
    for k in rng.choice(len(v), size=3, replace=False):
        v[k] += rng.choice([-1, 1]) * rng.uniform(0.15, 0.4)
    return Segment(s.source, s.group, v, s.c, s.T, s.t, s.vmin, s.vmax)


def _dropout(s: Segment, rng: np.random.Generator) -> Segment:
    v = s.v.copy()
    k = int(rng.integers(0, len(v) - 3))
    v[k:k + int(rng.integers(1, 4))] = 0.0
    return Segment(s.source, s.group, v, s.c, s.T, s.t, s.vmin, s.vmax)


def _voltage_drift(s: Segment, rng: np.random.Generator) -> Segment:
    ramp = np.linspace(0, rng.uniform(0.05, 0.15), len(s.v))  # 50-150 mV per cell over the record
    return Segment(s.source, s.group, s.v + ramp, s.c, s.T, s.t, s.vmin, s.vmax)


def _temperature_drift(s: Segment, rng: np.random.Generator) -> Segment:
    ramp = np.linspace(0, rng.uniform(5, 15), len(s.T))
    return Segment(s.source, s.group, s.v, s.c, s.T + ramp, s.t, s.vmin, s.vmax)


INJECTIONS: dict[str, Callable[[Segment, np.random.Generator], Segment]] = {
    "voltage_spikes": _spike,
    "voltage_dropout": _dropout,
    "voltage_drift": _voltage_drift,
    "temperature_drift": _temperature_drift,
}


def _folds(segs: list[Segment], k: int) -> list[set[str]]:
    groups = sorted({s.group for s in segs})
    rng = np.random.default_rng(SEED)
    perm = [str(g) for g in rng.permutation(groups)]
    return [set(perm[i::k]) for i in range(k)]


def _rate(x: float, prov: str, **kw: Any) -> dict[str, Any]:
    return {"value": round(float(x), 4), "provenance": prov, **kw}


def _evaluate_family(segs: list[Segment], k: int, prov: str) -> dict[str, Any]:
    """Grouped K-fold: fit on k-1 folds of groups, evaluate on the held-out groups."""
    feats = [s.features() for s in segs]
    rng = np.random.default_rng(SEED + 1)
    clean_q: dict[str, list[bool]] = {}
    win_flags: list[bool] = []
    det: dict[str, list[bool]] = {name: [] for name in INJECTIONS}
    for test_groups in _folds(segs, k):
        tr = [f for s, f in zip(segs, feats, strict=True) if s.group not in test_groups]
        model = OODFilter.fit(pd.concat(tr, ignore_index=True), seed=SEED)
        for s, f in zip(segs, feats, strict=True):
            if s.group not in test_groups:
                continue
            d = model.decide(f)
            clean_q.setdefault(s.group, []).append(d["status"] == "quarantine")
            win_flags.extend((model.score(f) < model.thr_flag).tolist())
            for name, fn in INJECTIONS.items():
                det[name].append(model.decide(fn(s, rng).features())["status"] == "quarantine")
    allq = [x for v in clean_q.values() for x in v]
    return {
        "folds": k,
        "segments": len(segs),
        "groups": len(clean_q),
        "clean_quarantine_rate": _rate(np.mean(allq), prov, note="held-out clean segments quarantined"),
        "clean_quarantine_rate_by_group": {g: _rate(np.mean(v), prov) for g, v in sorted(clean_q.items())},
        "clean_window_flag_rate": _rate(np.mean(win_flags), prov),
        "detection_rate": {n: _rate(np.mean(v), prov, note="held-out segments quarantined after injection")
                           for n, v in det.items()},
    }


FAMILIES: dict[str, dict[str, Any]] = {
    "measured_cells": {"provenance": "measured", "folds": 12,
                       "trained_on": "NASA PCoE B0005-7, B0018, B0025-32, cycles >= 1.6 Ah (measured)"},
    "synthetic_packs": {"provenance": "synthetic", "folds": 5,
                        "trained_on": "revive_ml.synth clean LFP/NMC packs, 150 seeds (synthetic)"},
}


def train_and_validate() -> dict[str, Any]:
    from revive_ml.gate.ood import MODEL_PATHS

    segments = {"measured_cells": nasa_segments(), "synthetic_packs": synthetic_segments()}
    report: dict[str, Any] = {"families": {}}
    for fam, segs in segments.items():
        cfg = FAMILIES[fam]
        ev = _evaluate_family(segs, cfg["folds"], cfg["provenance"])
        X = pd.concat([s.features() for s in segs], ignore_index=True)
        summary = {"family": fam, "trained_on": cfg["trained_on"], "provenance": cfg["provenance"],
                   "train_windows": len(X), "validation": {
                       "clean_quarantine_rate": ev["clean_quarantine_rate"]["value"],
                       "detection_rate": {k: v["value"] for k, v in ev["detection_rate"].items()}}}
        model = OODFilter.fit(X, seed=SEED, summary=summary)
        model.save(MODEL_PATHS[fam])
        report["families"][fam] = {"trained_on": cfg["trained_on"], "train_windows": len(X),
                                   "grouped_cv": ev}
    report["note"] = ("Grouped K-fold: cells (NASA) or seeds (synthetic) never cross train/test. "
                      "'measured' rates come from real NASA cell data; 'synthetic' rates from simulated "
                      "packs. Injections: 3 voltage spikes of 0.15-0.4 V/cell; a 1-3 row voltage dropout "
                      "to 0 V; a voltage ramp of 50-150 mV/cell over the record; a temperature ramp of "
                      "5-15 degC over the record. The filter is an out-of-distribution and sensor-noise "
                      "screen, not a fault detector.")
    REPORTS_DIR.mkdir(exist_ok=True)
    (REPORTS_DIR / "gate_validation.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report
