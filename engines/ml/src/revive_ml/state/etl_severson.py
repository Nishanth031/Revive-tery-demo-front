"""ETL for Severson et al. (2019) LFP cells: MATLAB v7.3 (HDF5) -> parquet.

Cleaning rules (all applied in code below and reported in data/processed/severson_cells.parquet):
  C1  Batch-2 cells that continue batch-1 cells are appended to the batch-1 cell (see the merge
      block for the pairing rule; every merge is logged in reports/severson_etl_log.json).
  C2  Cycle rows with zero or non-finite discharge capacity are dropped (cycle-0 artefacts).
  C3  End of life (EOL) = the authors' recorded cycle_life (the dataset label). As a cross-check,
      EOL is also computed as the first cycle whose 5-cycle rolling-median discharge capacity is at or
      below 0.88 Ah (80 % of the 1.1 Ah nominal, the paper's definition; 0.5 mAh tolerance because
      the cyclers stop on reaching it), or the last cycle when the test stopped at the threshold.
      Cells that never reach it are right-censored and excluded from RUL training.
  C4  Cells with more than 2 % of pre-EOL cycles showing capacity jumps > 0.05 Ah from the
      rolling median are flagged noisy and excluded.
Qdlin (discharge capacity interpolated on a fixed 1000-point voltage grid 3.6 -> 2.0 V) is kept
for every 10th cycle only, to bound disk use.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import h5py
import numpy as np
import pandas as pd

from revive_ml.paths import PROCESSED_DIR, REPORTS_DIR
from revive_ml.state.download import local_path

NOMINAL_AH = 1.1
EOL_AH = 0.88
EOL_TOL = 0.0005  # the cyclers stop on reaching 0.88 Ah; allow 0.5 mAh for that stopping rule
OPEN_AH = 0.90    # a batch-1 cell ending above this clearly had not reached EOL (continued later)
LABEL_CHECK_AH = 0.89  # a recorded cycle life is accepted only if capacity there is <= this
FULL_POLICY = re.compile(r"^\d+(\.\d+)?C\(")  # truncated continuation policies lack the first step
QDLIN_STRIDE = 10
BATCHES = {1: "severson_batch1", 2: "severson_batch2", 3: "severson_batch3"}
SUMMARY_FIELDS = {"QDischarge": "qd", "QCharge": "qc", "IR": "ir", "Tavg": "tavg", "Tmin": "tmin",
                  "Tmax": "tmax", "chargetime": "chargetime", "cycle": "cycle"}


def _read_batch(path: Path, batch: int) -> list[dict[str, Any]]:
    cells = []
    with h5py.File(path, "r") as f:
        b = f["batch"]
        for i in range(b["summary"].shape[0]):
            summ = f[b["summary"][i, 0]]
            s = {v: np.hstack(summ[k][0, :].tolist()).astype(float) for k, v in SUMMARY_FIELDS.items()}
            policy = f[b["policy_readable"][i, 0]][()].tobytes()[::2].decode()
            cl = np.asarray(f[b["cycle_life"][i, 0]][()]).ravel()
            cyc = f[b["cycles"][i, 0]]
            n = cyc["Qdlin"].shape[0]
            qdlin = {}
            for j in range(0, n, QDLIN_STRIDE):
                q = np.hstack(f[cyc["Qdlin"][j, 0]][()]).astype(np.float32)
                if q.size == 1000:
                    qdlin[j] = q
            cells.append({"cell": f"b{batch}c{i}", "batch": batch, "policy": policy,
                          "cycle_life_recorded": float(cl[0]) if cl.size and np.isfinite(cl[0]) else np.nan,
                          "summary": s, "n_cycles_raw": n, "qdlin": qdlin})
    return cells


def _summary_frame(c: dict[str, Any]) -> pd.DataFrame:
    df = pd.DataFrame(c["summary"])
    df["row"] = np.arange(len(df))
    return df


def run() -> dict[str, Any]:
    paths = {k: local_path(v) for k, v in BATCHES.items()}
    missing = [BATCHES[k] for k, p in paths.items() if p is None]
    if len(missing) == len(paths):
        raise FileNotFoundError("no Severson batch downloaded; run `revive-ml download`")
    raw: dict[int, list[dict[str, Any]]] = {k: _read_batch(p, k) for k, p in paths.items() if p}
    log: dict[str, Any] = {"missing_batches": missing, "merges": [], "excluded": {}}

    # C1: merge continuation cells. Batch-2 continuation files carry a truncated policy string
    # (e.g. "80%)-3.6C"). Within each policy group, batch-1 cells that had not reached EOL are
    # paired with truncated batch-2 cells in index order (the order the authors processed them;
    # barcodes are not readable strings in these files), and a pair is merged only if the
    # capacity is continuous (gap < 2 %). Unpaired or discontinuous cells are left separate.
    merged_away: set[str] = set()
    if 1 in raw and 2 in raw:
        open_b1 = []
        for c1 in raw[1]:
            s1 = _summary_frame(c1)
            s1 = s1[(s1.qd > 0) & np.isfinite(s1.qd)]
            if not s1.empty and s1.qd.iloc[-5:].median() > OPEN_AH:
                open_b1.append(c1)
        truncated = [c2 for c2 in raw[2] if not FULL_POLICY.match(c2["policy"])]
        for policy in sorted({c["policy"] for c in open_b1}):
            g1 = [c for c in open_b1 if c["policy"] == policy]
            g2 = [c for c in truncated if policy.endswith(c["policy"])]
            if len(g1) != len(g2):
                log.setdefault("unpaired_groups", []).append(policy)
                continue
            for c1, c2 in zip(g1, g2, strict=True):
                s1, s2 = _summary_frame(c1), _summary_frame(c2)
                last = s1.qd[s1.qd > 0].iloc[-5:].median()
                first = s2.qd[s2.qd > 0].iloc[:5].median()
                gap = abs(first - last) / last
                if gap >= 0.02:
                    log.setdefault("rejected_pairs", []).append([c1["cell"], c2["cell"], round(gap, 4)])
                    continue
                off = c1["n_cycles_raw"]
                for k, v in c1["summary"].items():
                    add = c2["summary"][k] + (off if k == "cycle" else 0)
                    c1["summary"][k] = np.concatenate([v, add])
                c1["qdlin"].update({off + j: q for j, q in c2["qdlin"].items()})
                c1["n_cycles_raw"] += c2["n_cycles_raw"]
                c1["continuation_cycle_life"] = c2["cycle_life_recorded"]
                merged_away.add(c2["cell"])
                log["merges"].append({"into": c1["cell"], "from": c2["cell"], "policy": c1["policy"],
                                      "capacity_gap_fraction": round(float(gap), 4)})

    summaries, qrows, cells_meta = [], [], []
    for batch_cells in raw.values():
        for c in batch_cells:
            if c["cell"] in merged_away:
                continue
            df = _summary_frame(c)
            df = df[(df.qd > 0) & np.isfinite(df.qd)].copy()  # C2
            df["cycle"] = df["row"]  # row index == cycle index (cycle 0 dropped by C2)
            med = df.qd.rolling(5, min_periods=1, center=True).median()
            below = np.flatnonzero(med.to_numpy() <= EOL_AH + EOL_TOL)
            eol_computed = int(df.cycle.iloc[below[0]]) if below.size else None
            recorded = c["cycle_life_recorded"]
            if "continuation_cycle_life" in c:
                # merged record: the batch-1 label covers batch 1 only; use the merged length
                cont = c["continuation_cycle_life"]
                recorded = float(c["n_cycles_raw"] - 1) if np.isfinite(cont) else np.nan
            # The authors' recorded cycle life is the label, accepted only when the data agree that
            # capacity has fallen to ~0.88 Ah by then; the computed EOL is a cross-check.
            eol = None
            reason = None
            if np.isfinite(recorded):
                at = med[df.cycle <= recorded]
                if len(at) and at.iloc[-1] <= LABEL_CHECK_AH:
                    eol = int(recorded)
                else:
                    reason = "censored: recorded cycle life not supported by capacity data"
            elif eol_computed is not None:
                eol = eol_computed
            if eol is None and reason is None:
                reason = "censored: never reaches 0.88 Ah"
            else:
                pre = df.cycle <= eol
                jumps = (np.abs(df.qd - med) > 0.05)[pre].mean()
                if jumps > 0.02:
                    reason = f"noisy: {jumps:.1%} of pre-EOL cycles jump > 0.05 Ah"
            cells_meta.append({"cell": c["cell"], "batch": c["batch"], "policy": c["policy"],
                               "cycle_life_recorded": recorded,
                               "eol_cycle": eol if eol is not None else np.nan,
                               "eol_cycle_computed": eol_computed if eol_computed is not None else np.nan,
                               "n_cycles": len(df), "excluded": reason})
            if reason:
                log["excluded"][c["cell"]] = reason
            df["cell"] = c["cell"]
            summaries.append(df.drop(columns="row"))
            for j, q in c["qdlin"].items():
                qrows.append({"cell": c["cell"], "cycle": j, "qdlin": q})

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    cells_df = pd.DataFrame(cells_meta)
    cells_df.to_parquet(PROCESSED_DIR / "severson_cells.parquet", index=False)
    summary = pd.concat(summaries, ignore_index=True)
    summary.to_parquet(PROCESSED_DIR / "severson_summary.parquet", index=False)
    pd.DataFrame(qrows).to_parquet(PROCESSED_DIR / "severson_qdlin.parquet", index=False)
    usable = cells_df[cells_df.excluded.isna()]
    agree = usable.dropna(subset=["cycle_life_recorded", "eol_cycle_computed"])
    log.update({
        "cells_read": len(cells_df) + len(merged_away),
        "cells_after_merge": len(cells_df),
        "cells_usable": len(usable),
        "eol_vs_recorded_cycle_life_median_abs_diff": float(
            np.median(np.abs(agree.eol_cycle_computed - agree.cycle_life_recorded))) if len(agree) else None,
    })
    REPORTS_DIR.mkdir(exist_ok=True)
    text = json.dumps(log, indent=2, default=str)
    (REPORTS_DIR / "severson_etl_log.json").write_text(text, encoding="utf-8")
    return {k: log[k] for k in ("cells_read", "cells_after_merge", "cells_usable")} | {
        "merges": len(log["merges"]), "excluded": len(log["excluded"])}
