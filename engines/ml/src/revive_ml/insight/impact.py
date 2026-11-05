"""Fleet impact: energy redeployed and value vs recycling everything now. Every number is tagged modelled or assumed.

Input: compact per-pack records {disposition, net_value (best second-life net USD or None), recycle_value (USD),
pack_kwh, soh (%)} as written by the fleet builders. Synthetic fleets give synthetic-based numbers: say so.
"""
from __future__ import annotations

from typing import Any

from revive_ml.provenance import tag

SECOND = ("REUSE", "REPURPOSE")


def impact(packs: list[dict[str, Any]]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for p in packs:
        counts[p["disposition"]] = counts.get(p["disposition"], 0) + 1
    second = [p for p in packs if p["disposition"] in SECOND]
    kwh = sum(p["pack_kwh"] * p["soh"] / 100 for p in second if p.get("pack_kwh") and p.get("soh") is not None)
    routed = sum(p["net_value"] or 0 for p in second) + sum(p.get("recycle_value") or 0 for p in packs if p not in second)
    recycle_all = sum(p.get("recycle_value") or 0 for p in packs)
    return {
        "packs": tag(len(packs), "modelled", "packs"),
        "count_by_disposition": counts,
        "kwh_redeployed": tag(kwh, "modelled", "kWh", note="pack kWh x SOH for packs routed to a second life"),
        "net_value_routed": tag(routed, "modelled", "USD", note="engine routing; placeholder cost and tariff inputs"),
        "net_value_recycle_all": tag(recycle_all, "modelled", "USD", note="every pack recycled now"),
        "value_vs_recycle_all": tag(routed - recycle_all, "modelled", "USD"),
    }


def scale(imp: dict[str, Any], n_packs: int) -> dict[str, Any]:
    """Linear scale-up of an impact result to n_packs. Illustrative only."""
    n0 = imp["packs"]["value"] or 1
    f = n_packs / n0
    return {
        "n_packs": tag(n_packs, "assumed", "packs"),
        "kwh_redeployed": tag(imp["kwh_redeployed"]["value"] * f, "modelled", "kWh"),
        "value_vs_recycle_all": tag(imp["value_vs_recycle_all"]["value"] * f, "modelled", "USD"),
        "assumptions": [
            "the scaled fleet has the same mix of chemistries, health and dispositions as this one",
            "prices, tariffs and costs stay at today's (partly PLACEHOLDER) values",
            "no market effect: second-life demand absorbs every routed pack",
            "this fleet is SYNTHETIC, so the result shows the pipeline, not a real market size",
        ],
    }
