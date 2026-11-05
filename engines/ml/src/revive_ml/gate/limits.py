"""Deterministic chemistry-specific limits (gate stage a)."""

from __future__ import annotations

from typing import Any

import numpy as np

from revive_ml.config import load
from revive_ml.contract import Bundle
from revive_ml.provenance import data_provenance_tag, tag


def check_limits(bundle: Bundle) -> dict[str, Any]:
    cfg = load("limits.yaml")
    meta = bundle.meta
    lim = cfg["chemistries"][meta.chemistry]
    common = cfg["common"]
    prov = data_provenance_tag(meta.data_provenance)
    df = bundle.telemetry
    series = meta.series_cells
    breaches: list[dict[str, Any]] = []
    notes: list[str] = []
    v = df["voltage_v"].to_numpy(float)
    if series:
        vc = v / series
        for key, op in (("cell_v_min", np.less), ("cell_v_max", np.greater)):
            hit = op(vc, lim[key]["value"]) & np.isfinite(vc)
            if hit.sum() >= common["min_rows_beyond_limit"]:
                worst = float(np.nanmin(vc[hit]) if key == "cell_v_min" else np.nanmax(vc[hit]))
                breaches.append({"limit": key, "rows": int(hit.sum()),
                                 "observed": tag(worst, prov, "V/cell", note="pack voltage / series"),
                                 "threshold": tag(lim[key]["value"], "assumed", "V/cell",
                                                  source=lim[key]["source"])})
        notes.append("voltage limits applied to the pack-average cell; weak cells can be hidden")
    else:
        notes.append("series count unknown: cell voltage limits not applied")
    t = df["temperature_c"].to_numpy(float)
    for key, op in (("temp_max_c", np.greater), ("temp_min_c", np.less)):
        hit = op(t, lim[key]["value"]) & np.isfinite(t)
        if hit.sum() >= common["min_rows_beyond_limit"]:
            worst = float(np.nanmax(t[hit]) if key == "temp_max_c" else np.nanmin(t[hit]))
            breaches.append({"limit": key, "rows": int(hit.sum()),
                             "observed": tag(worst, prov, "degC"),
                             "threshold": tag(lim[key]["value"], "assumed", "degC",
                                              source=lim[key]["source"])})
    rts = sorted(meta.resistance_tests, key=lambda x: (x.date, x.cycle_count or 0))
    if len(rts) >= 2:
        ratio = rts[-1].resistance_mohm / rts[0].resistance_mohm
        thr = common["resistance_ratio_reject"]["value"]
        if ratio >= thr:
            breaches.append({"limit": "resistance_ratio", "rows": 0,
                             "observed": tag(ratio, data_provenance_tag(rts[-1].provenance),
                                             note="latest / earliest resistance test"),
                             "threshold": tag(thr, "assumed",
                                              source=common["resistance_ratio_reject"]["source"])})
    quarantine_events = [
        {"event_type": e.event_type, "severity": e.severity, "status": e.status}
        for e in meta.safety_events
        if e.severity.upper() in common["open_safety_event_severities_quarantine"]
        and (e.status or "").upper() != "CLOSED"
    ]
    return {"breaches": breaches, "open_safety_events": quarantine_events, "notes": notes,
            "chemistry": meta.chemistry}
