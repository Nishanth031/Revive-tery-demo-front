"""Fleet plan: assign packs to applications to maximise total net value under per-application limits.

Input per pack: {asset_id, eligible, options: {application: net USD}, recycle: net USD, kwh}. Only eligible packs
(disposition Reuse/Repurpose) are assigned; the rest stay out (their recycle value is still counted). A pack that is
not given an application is recycled. Limits per application: {"packs": n} and/or {"kwh": x}.

Algorithm (same in Python and JS): greedy by gain over recycling, then a 2-opt pass (move a pack to a free slot, or
swap two packs' applications) until no move improves the total. Python also reports the exact optimum for pack-count
limits with scipy.optimize.linear_sum_assignment, when scipy is installed, as a check.
"""
from __future__ import annotations

from typing import Any

MAX_PASSES = 20


def _fits(app: str, used: dict[str, dict[str, float]], kwh: float, limits: dict[str, dict[str, float]]) -> bool:
    lim = limits.get(app)
    if lim is None:
        return False
    if "packs" in lim and used[app]["packs"] + 1 > lim["packs"]:
        return False
    if "kwh" in lim and used[app]["kwh"] + kwh > lim["kwh"] + 1e-9:
        return False
    return True


def _total(packs, plan) -> float:
    return sum((p["options"][plan[p["asset_id"]]] if plan.get(p["asset_id"]) else p["recycle"]) for p in packs)


def assign(packs: list[dict[str, Any]], limits: dict[str, dict[str, float]]) -> dict[str, Any]:
    packs = sorted(packs, key=lambda p: p["asset_id"])
    elig = [p for p in packs if p.get("eligible")]
    used = {a: {"packs": 0, "kwh": 0.0} for a in limits}
    plan: dict[str, str | None] = {p["asset_id"]: None for p in packs}
    cand = sorted(((p["options"][a] - p["recycle"], p["asset_id"], a, p) for p in elig for a in p["options"] if a in limits),
                  key=lambda c: (-c[0], c[1], c[2]))
    for gain, aid, a, p in cand:
        if gain <= 0 or plan[aid] is not None or not _fits(a, used, p["kwh"], limits):
            continue
        plan[aid] = a
        used[a]["packs"] += 1
        used[a]["kwh"] += p["kwh"]
    greedy_value = _total(packs, plan)

    def val(p, a):
        return p["options"][a] if a else p["recycle"]

    for _ in range(MAX_PASSES):
        improved = False
        for p in elig:                                        # move to a free slot (or out)
            cur = plan[p["asset_id"]]
            for a in [*sorted(p["options"]), None]:
                if a == cur or (a and a not in limits):
                    continue
                if a and not _fits(a, used, p["kwh"], limits):
                    continue
                if val(p, a) > val(p, cur) + 1e-9:
                    if cur:
                        used[cur]["packs"] -= 1
                        used[cur]["kwh"] -= p["kwh"]
                    if a:
                        used[a]["packs"] += 1
                        used[a]["kwh"] += p["kwh"]
                    plan[p["asset_id"]] = cur = a
                    improved = True
        for i, p in enumerate(elig):                          # swap two packs' applications
            for q in elig[i + 1:]:
                a, b = plan[p["asset_id"]], plan[q["asset_id"]]
                if a == b or (a and a not in q["options"]) or (b and b not in p["options"]):
                    continue
                gain = val(p, b) + val(q, a) - val(p, a) - val(q, b)
                if gain <= 1e-9:
                    continue
                dk = q["kwh"] - p["kwh"]                       # kWh change for app a (q replaces p) and b
                ok = (not a or "kwh" not in limits[a] or used[a]["kwh"] + dk <= limits[a]["kwh"] + 1e-9) and \
                     (not b or "kwh" not in limits[b] or used[b]["kwh"] - dk <= limits[b]["kwh"] + 1e-9)
                if ok:
                    if a:
                        used[a]["kwh"] += dk
                    if b:
                        used[b]["kwh"] -= dk
                    plan[p["asset_id"]], plan[q["asset_id"]] = b, a
                    improved = True
        if not improved:
            break
    total = _total(packs, plan)
    per_pack_best = sum(max([p["recycle"], *[v for a, v in p["options"].items()]]) if p.get("eligible") else p["recycle"]
                        for p in packs)
    out = {
        "plan": [{"asset_id": aid, "application": a} for aid, a in plan.items() if a],
        "by_application": {a: {"packs": round(u["packs"]), "kwh": round(u["kwh"], 3), "limit": limits[a]} for a, u in used.items()},
        "total_value": total, "greedy_value": greedy_value,
        "per_pack_greedy_value": per_pack_best, "value_gap_vs_per_pack_greedy": per_pack_best - total,
        "algorithm": "greedy + 2-opt", "provenance": "modelled",
    }
    out["exact_total"] = _exact(packs, limits)
    return out


def _exact(packs, limits) -> float | None:
    """Exact optimum for pack-count limits only (scipy linear_sum_assignment); None otherwise."""
    if any("kwh" in lim or "packs" not in lim for lim in limits.values()):
        return None
    try:
        import numpy as np
        from scipy.optimize import linear_sum_assignment
    except ImportError:
        return None
    elig = [p for p in packs if p.get("eligible")]
    slots = [a for a, lim in sorted(limits.items()) for _ in range(int(lim["packs"]))]
    if not elig or not slots:
        return sum(p["recycle"] for p in packs)
    gain = np.zeros((len(elig), len(slots) + len(elig)))      # extra columns = "stay recycled" (gain 0)
    for i, p in enumerate(elig):
        for j, a in enumerate(slots):
            gain[i, j] = p["options"].get(a, -1e18) - p["recycle"]
    r, c = linear_sum_assignment(-gain)
    return float(sum(p["recycle"] for p in packs) + sum(max(0.0, gain[i, j]) for i, j in zip(r, c) if j < len(slots)))
