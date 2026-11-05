"""Safety gate: deterministic limits -> Reject; OOD filter -> Quarantine; else Pass."""

from __future__ import annotations

from typing import Any

from revive_ml.config import load
from revive_ml.contract import Bundle
from revive_ml.gate.limits import check_limits


def evaluate(bundle: Bundle, ood_model: Any | None = None) -> dict[str, Any]:
    wording = load("limits.yaml")["wording"]
    lim = check_limits(bundle)
    out: dict[str, Any] = {"wording": wording, "limits": lim}
    if lim["breaches"]:
        out["verdict"] = "Reject"
        out["reasons"] = [f"{b['limit']} breached on {b['rows']} row(s)" for b in lim["breaches"]]
        out["ood"] = {"status": "not run: limits already rejected"}
        return out
    if ood_model is None:
        from revive_ml.gate.ood import family_for, load_default

        ood_model = load_default(family_for(bundle))
    if ood_model is not None:
        ood = ood_model.assess(bundle)
    else:
        ood = {"status": "unavailable", "note": "no trained OOD model; run `revive-ml train-gate`"}
    out["ood"] = ood
    reasons = []
    if lim["open_safety_events"]:
        reasons.append(f"{len(lim['open_safety_events'])} open high-severity safety event(s)")
    if ood.get("status") == "quarantine":
        reasons.append(ood["reason"])
    if ood.get("status") == "unavailable":
        reasons.append("OOD filter unavailable; cannot clear the battery for second life")
    if reasons:
        out["verdict"] = "Quarantine"
        out["reasons"] = reasons
    else:
        out["verdict"] = "Pass"
        out["reasons"] = ["no hard-limit breach; telemetry inside the healthy-window distribution"]
    return out
