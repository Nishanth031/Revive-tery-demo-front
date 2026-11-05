"""Value of information: concrete next steps that would change or firm up the decision, each with its evidence.

Never promises a number it cannot compute: effects are stated in words ("expected to narrow"), except the
break-even tariff, which is computed by whatif.break_even.
"""
from __future__ import annotations

from typing import Any

from revive_ml.insight.whatif import break_even

NEEDS_TEXT = {"chemistry": "the cell chemistry (LFP, NMC or NCA)", "series_cells": "the series cell count",
              "rated_capacity_ah": "the rated capacity", "timestamps": "timestamps for every reading"}


def next_best_actions(report: dict[str, Any], still_needs: list[str] | None = None) -> list[dict[str, str]]:
    acts: list[dict[str, str]] = []
    for n in still_needs or []:
        acts.append({"action": f"Supply {NEEDS_TEXT.get(n, n)}", "why": "the ML could not establish it from the upload",
                     "expected_effect": "lets the full engine run instead of refusing or using a default"})
    checks = (report.get("data_quality") or {}).get("checks", [])
    for c in checks:
        if c["status"] == "fail":
            acts.append({"action": f"Fix the data behind '{c['id']}'", "why": c["message"],
                         "expected_effect": "the engine can then judge health from data it trusts"})
    g = report.get("gate") or {}
    if g.get("verdict") == "Quarantine":
        acts.append({"action": "Inspect the pack before any second-life use", "why": "; ".join(g.get("reasons", [])),
                     "expected_effect": "clears or confirms the quarantine; the economics then run"})
    st = report.get("state") or {}
    r = st.get("rul_cycles_reference")
    if isinstance(r, dict) and r.get("value"):
        width = ((r.get("upper") or 0) - (r.get("lower") or 0)) / r["value"]
        if width > 0.5:
            acts.append({"action": "Add a recent full capacity test",
                         "why": f"the remaining-life interval spans {(r.get('lower') or 0):.0f}-{(r.get('upper') or 0):.0f} cycles "
                                f"({width:.0%} of the median)",
                         "expected_effect": "expected to narrow the remaining-life interval and the years-to-limit range"})
    res = next((c for c in checks if c["id"] == "resistance"), None)
    if res and res["status"] != "pass":
        acts.append({"action": "Add a pack DC-resistance test", "why": res["message"],
                     "expected_effect": "lets resistance growth count in the safety gate and the state estimate"})
    if report.get("chemistry") and report["chemistry"] != "LFP" and st:
        acts.append({"action": f"Validate on {report['chemistry']} cells",
                     "why": "the state model was trained on LFP cells; its interval coverage does not apply here",
                     "expected_effect": "would turn the remaining-life numbers from indicative into checked ones"})
    be = break_even(report, "tariff")
    if be:
        direction = "above" if be["above"] != be["current"] else "below"
        target = be["above"] if direction == "above" else be["below"]
        acts.append({"action": f"Check the real tariff: {direction} {be['value']:.3f} USD/kWh the decision becomes {target}",
                     "why": f"today's tariff {be['current_value']:.3f} USD/kWh is a PLACEHOLDER input",
                     "expected_effect": "confirms or flips the economics decision"})
    return acts
