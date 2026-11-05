"""The existing REVIVE-TERY routing rule, kept only for comparison with the ML routing."""

from __future__ import annotations


def rule_route(soh_pct: float | None) -> str:
    if soh_pct is None:
        return "Insufficient data"  # no measured capacity
    if soh_pct > 80:
        return "Second-Life: stationary storage"
    if soh_pct >= 60:
        return "Second-Life: low-speed EV"
    return "Recycle"
