"""What-if, break-even and robustness: re-run ONLY the economics stage (econ.router.route) on a modified copy of the
economics config. The data-quality, gate, state and projection results of the report are reused as they are.

Levers: tariff (second_life.value_per_kwh_delivered, USD/kWh), cost_mult (testing, refurbishment, logistics,
installation), metal_mult (nickel, cobalt, lithium carbonate prices), new_cost (installed system USD/kWh),
discount_rate, region (economics.yaml second_life.regions), workloads (subset of application keys).
"""
from __future__ import annotations

import copy
import itertools
from types import SimpleNamespace
from typing import Any

from revive_ml.config import load
from revive_ml.econ.router import route, with_region
from revive_ml.insight.explain import val

COST_KEYS = ("testing_usd_per_kwh", "refurbishment_usd_per_kwh", "logistics_usd_per_kwh", "installation_usd_per_kwh")
METALS = ("nickel", "cobalt", "lithium_carbonate")
LEVERS = ("tariff", "cost_mult", "metal_mult", "new_cost", "discount_rate")


def config_with(overrides: dict[str, Any], base: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = copy.deepcopy(base or load("economics.yaml"))
    cfg = with_region(cfg, overrides.get("region"))
    if overrides.get("tariff") is not None:
        cfg["second_life"]["value_per_kwh_delivered"] = {**cfg["second_life"]["value_per_kwh_delivered"],
                                                         "value": float(overrides["tariff"])}
    if overrides.get("cost_mult") is not None:
        for k in COST_KEYS:
            cfg["second_life"][k] = {**cfg["second_life"][k], "value": val(cfg["second_life"][k]) * float(overrides["cost_mult"])}
    if overrides.get("metal_mult") is not None:
        p = cfg["recycling"]["prices_usd_per_tonne"]
        for m in METALS:
            p[m] = {**p[m], "value": val(p[m]) * float(overrides["metal_mult"])}
    if overrides.get("new_cost") is not None:
        b = cfg["buy_new_benchmark"]
        b["installed_system_usd_per_kwh"] = {**b["installed_system_usd_per_kwh"], "value": float(overrides["new_cost"])}
    if overrides.get("discount_rate") is not None:
        cfg["discount_rate"] = {**cfg["discount_rate"], "value": float(overrides["discount_rate"])}
    return cfg


def can_reroute(report: dict[str, Any]) -> bool:
    return bool(report.get("economics")) and bool(report.get("projections")) and \
        (report.get("state") or {}).get("status") == "ok"


def reroute(report: dict[str, Any], overrides: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """The economics decision under overrides; None when the report never reached the economics stage."""
    if not can_reroute(report):
        return None
    overrides = overrides or {}
    pack_kwh = val(report["economics"]["pack_energy"])
    meta = SimpleNamespace(nominal_voltage_v=pack_kwh * 1000.0, rated_capacity_ah=1.0, chemistry=report["chemistry"])
    proj = report["projections"]
    if overrides.get("workloads"):
        proj = {k: v for k, v in proj.items() if k in set(overrides["workloads"])}
    e = route(meta, report["state"], proj, config_with(overrides))
    opts = e.get("second_life_options") or {}
    return {"decision": e["decision"], "application": (e.get("recommendation") or {}).get("application"),
            "best_net": max((val(o["net_value"]) for o in opts.values()), default=None),
            "recycle_net": val(e["recycle"]["net_value"]),
            "options": {k: val(o["net_value"]) for k, o in opts.items()}}


def _cls(decision: str) -> str:
    return decision.split(":")[0]


def _base_value(lever: str) -> float:
    cfg = load("economics.yaml")
    return {"tariff": val(cfg["second_life"]["value_per_kwh_delivered"]), "cost_mult": 1.0, "metal_mult": 1.0,
            "new_cost": val(cfg["buy_new_benchmark"]["installed_system_usd_per_kwh"]),
            "discount_rate": val(cfg["discount_rate"])}[lever]


def break_even(report: dict[str, Any], lever: str = "tariff", overrides: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """The lever value where the decision class (Second-Life <-> Recycle) changes, nearest to today's value.
    Grid search then bisection, at most `break_even.max_evaluations` route() calls. None if no flip in range."""
    cfg = load("intelligence.yaml")["break_even"]
    lo, hi = cfg[f"{lever}_range"]
    budget = int(cfg["max_evaluations"])
    base = dict(overrides or {})
    now = reroute(report, base)
    if now is None:
        return None
    cur = _cls(now["decision"])
    n_grid = 16
    xs = [lo + (hi - lo) * i / (n_grid - 1) for i in range(n_grid)]
    cls = [_cls(reroute(report, {**base, lever: x})["decision"]) for x in xs]
    used = 1 + n_grid
    b0 = base.get(lever, _base_value(lever))
    pairs = [(i, abs((xs[i] + xs[i + 1]) / 2 - b0)) for i in range(n_grid - 1) if cls[i] != cls[i + 1]]
    if not pairs:
        return None
    i = min(pairs, key=lambda p: p[1])[0]
    a, b, ca = xs[i], xs[i + 1], cls[i]
    while used < budget:
        m = (a + b) / 2
        cm = _cls(reroute(report, {**base, lever: m})["decision"])
        used += 1
        if cm == ca:
            a = m
        else:
            b = m
    below, above = cls[i], cls[i + 1]
    return {"lever": lever, "value": (a + b) / 2, "below": below, "above": above, "current": cur,
            "current_value": b0, "evaluations": used}


def robustness(report: dict[str, Any], grid: dict[str, list[float]] | None = None) -> dict[str, Any] | None:
    """Share of the configured grid (full factorial) that keeps today's decision class, per-lever ranges that keep it
    (one lever at a time), the flips, and today's break-even tariff."""
    now = reroute(report)
    if now is None:
        return None
    grid = grid or {k: v for k, v in load("intelligence.yaml")["robustness"].items()}
    cur = _cls(now["decision"])
    keys = list(grid)
    same = total = 0
    for combo in itertools.product(*(grid[k] for k in keys)):
        total += 1
        same += _cls(reroute(report, dict(zip(keys, combo)))["decision"]) == cur
    per_lever, flips = {}, []
    for k in keys:
        keep = []
        for x in grid[k]:
            d = reroute(report, {k: x})["decision"]
            if _cls(d) == cur:
                keep.append(x)
            else:
                flips.append({"lever": k, "value": x, "decision": d})
        per_lever[k] = [min(keep), max(keep)] if keep else None
    be = break_even(report, "tariff")
    return {"current_decision": now["decision"], "share_same_decision": same / total if total else None,
            "scenarios": total, "per_lever_range": per_lever, "flips": flips,
            "break_even_tariff": be["value"] if be else None, "grid": grid, "label": "assumption sweep, not a probability"}
