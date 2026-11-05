"""Overall data-readiness verdict from explicit rules (no weighted score).

Rules, applied in order:
  R1  any check `fail`                         -> NOT_READY
  R2  any check `warn` or `inconclusive`       -> READY_WITH_WARNINGS
  R3  otherwise                                -> READY
`inconclusive` is never treated as a pass: the quantity it concerns is excluded from decisions.
"""

from __future__ import annotations

from typing import Any

from revive_ml.dq.detectors import CheckResult

RULES = [
    "R1: any check with status 'fail' -> NOT_READY",
    "R2: else any 'warn' or 'inconclusive' -> READY_WITH_WARNINGS",
    "R3: else -> READY",
]


def readiness(checks: list[CheckResult]) -> dict[str, Any]:
    counts = {s: sum(c.status == s for c in checks)
              for s in ("pass", "warn", "fail", "inconclusive", "not_applicable")}
    fails = [c.id for c in checks if c.status == "fail"]
    soft = [c.id for c in checks if c.status in ("warn", "inconclusive")]
    if fails:
        verdict, rule, why = "NOT_READY", RULES[0], fails
    elif soft:
        verdict, rule, why = "READY_WITH_WARNINGS", RULES[1], soft
    else:
        verdict, rule, why = "READY", RULES[2], []
    return {
        "verdict": verdict,
        "rule_applied": rule,
        "triggering_checks": why,
        "rules": RULES,
        "n_checks": len(checks),
        **{f"n_{k}": v for k, v in counts.items()},
        "excluded_from_decision": [c.id for c in checks if c.status == "inconclusive"],
    }
