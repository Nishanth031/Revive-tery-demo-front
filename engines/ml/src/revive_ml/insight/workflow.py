"""assess_with_insight: the unchanged engine report plus a new `insight` key."""
from __future__ import annotations

from typing import Any

from revive_ml.insight.confidence import confidence
from revive_ml.insight.explain import explain, rule_gap
from revive_ml.insight.voi import next_best_actions
from revive_ml.insight.whatif import robustness


def insight_for(report: dict[str, Any], bundle: Any = None, still_needs: list[str] | None = None,
                with_robustness: bool = True) -> dict[str, Any]:
    reasons = explain(report)
    n_rows = len(bundle.telemetry) if bundle is not None and getattr(bundle, "telemetry", None) is not None else None
    conf = confidence(report, n_rows)
    return {
        "reasons": reasons,
        "confidence": {k: conf[k] for k in ("level", "score_0_100", "factors", "label")},
        "rul_range": conf["rul_range"],
        "years_range": conf["years_range"],
        "robustness": robustness(report) if with_robustness else None,
        "next_actions": next_best_actions(report, still_needs),
        "rule_gap": rule_gap(report, reasons),
    }


def assess_with_insight(bundle: Any, region: str | None = None, workloads: dict[str, Any] | None = None) -> dict[str, Any]:
    from revive_ml.pipeline import assess

    report = assess(bundle, workloads, region=region)
    return {**report, "insight": insight_for(report, bundle)}
