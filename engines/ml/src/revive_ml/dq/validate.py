"""Detector validation: detection rate on injected faults, false-positive rate on clean data."""

from __future__ import annotations

import json
from typing import Any

import numpy as np

from revive_ml.dq.detectors import run_all
from revive_ml.dq.inject import FAULTS, random_clean_bundle
from revive_ml.dq.readiness import readiness
from revive_ml.paths import REPORTS_DIR

# Statuses that are expected on clean SYNTHETIC data and are therefore not false positives:
# the provenance check always warns on synthetic data, by design.
EXPECTED_ON_CLEAN = {("provenance", "warn")}


def validate(n: int = 30, seed0: int = 0) -> dict[str, Any]:
    detection: dict[str, Any] = {}
    fp_counts: dict[str, int] = {}
    not_ready_clean = 0
    for s in range(seed0, seed0 + n):
        clean = random_clean_bundle(s)
        checks = run_all(clean)
        if readiness(checks)["verdict"] == "NOT_READY":
            not_ready_clean += 1
        for c in checks:
            flagged = (c.status in ("warn", "fail", "inconclusive")
                       and (c.id, c.status) not in EXPECTED_ON_CLEAN)
            fp_counts[c.id] = fp_counts.get(c.id, 0) + int(flagged)
        for name, (inject, det, statuses) in FAULTS.items():
            faulty = inject(clean, np.random.default_rng(s))
            res = {c.id: c.status for c in run_all(faulty)}
            d = detection.setdefault(name, {"detector": det, "detected": 0, "trials": 0,
                                            "statuses": {}})
            d["trials"] += 1
            d["detected"] += int(res[det] in statuses)
            d["statuses"][res[det]] = d["statuses"].get(res[det], 0) + 1
    for d in detection.values():
        d["detection_rate"] = {"value": d["detected"] / d["trials"], "provenance": "synthetic",
                               "note": "on injected faults in synthetic bundles"}
    fp = {k: {"value": v / n, "provenance": "synthetic", "flagged": v} for k, v in fp_counts.items()}
    out = {
        "n_clean_bundles": n,
        "note": ("All bundles are SYNTHETIC (revive_ml.synth) with randomised chemistry (LFP/NMC), "
                 "sampling step (1-30 s), SOH, ambient temperature and noise. Rates show the "
                 "detectors work on the faults they were designed for; they are not field "
                 "performance figures."),
        "detection": detection,
        "false_positive_rate_per_detector": fp,
        "clean_bundles_marked_not_ready": {"value": not_ready_clean / n, "provenance": "synthetic"},
    }
    return out


# Seeds 0-39 were used while developing the detectors (one false-positive source, SOC
# quantisation in the stuck check, was found and fixed on them). Reported numbers use
# held-out seeds starting at 1000 that were not looked at during development.
HELD_OUT_SEED0 = 1000


def write_report(n: int = 100) -> dict[str, Any]:
    out = validate(n, seed0=HELD_OUT_SEED0)
    out["seeds"] = f"held-out {HELD_OUT_SEED0}..{HELD_OUT_SEED0 + n - 1} (development used 0..39)"
    REPORTS_DIR.mkdir(exist_ok=True)
    (REPORTS_DIR / "dq_validation.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    return out
