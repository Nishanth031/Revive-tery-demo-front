"""/api/fleet, /api/battery/{id}, /api/whatif, /api/meta, /api/history/*: the fleet behind the Command Center.

Read-only GETs except POST /api/whatif (computes, writes nothing), POST /api/fleet/plan (computes) and
POST /api/fleet/refresh (the single writer of fleet_reports). Mounted from main.py.
"""
from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, FastAPI, HTTPException
from pydantic import BaseModel, Field

from .services import fleet as svc

router = APIRouter(prefix="/api", tags=["fleet"])


class WhatIfIn(BaseModel):
    asset_id: str = Field(min_length=1)
    overrides: dict[str, float] = Field(default_factory=dict, description="tariff, cost_mult, metal_mult, new_cost, discount_rate")
    region: str | None = None


class PlanIn(BaseModel):
    limits: dict[str, dict[str, float]] = Field(description='per application: {"packs": n} and/or {"kwh": x}')


@router.get("/fleet")
def fleet(q: str | None = None, decision: str | None = None, disposition: str | None = None, chemistry: str | None = None,
          source: Literal["user", "platform", "test"] | None = None,
          sort: Literal["net_value", "soh", "confidence", "asset_id"] = "asset_id", desc: bool = False,
          offset: int = 0, limit: int = 25, compact: bool = True) -> dict[str, Any]:
    return svc.query(q, decision, disposition, chemistry, source, sort, desc, max(0, offset), max(1, min(limit, 1000)))


@router.get("/fleet/summary")
def fleet_summary() -> dict[str, Any]:
    return svc.summary()


@router.post("/fleet/plan")
def fleet_plan(req: PlanIn) -> dict[str, Any]:
    return svc.plan(req.limits)


@router.post("/fleet/refresh", status_code=201)
def fleet_refresh() -> dict[str, Any]:
    return svc.refresh()


@router.get("/battery/{asset_id}")
def battery(asset_id: str) -> dict[str, Any]:
    return svc.battery(asset_id)


@router.get("/battery/{asset_id}/history")
def battery_history(asset_id: str) -> list[dict[str, Any]]:
    return svc.history(asset_id)


@router.get("/battery/{asset_id}/passport")
def battery_passport(asset_id: str) -> dict[str, Any]:
    return svc.battery_passport(asset_id)


@router.post("/whatif")
def whatif(req: WhatIfIn) -> dict[str, Any]:
    try:
        return svc.whatif(req.asset_id, req.overrides, req.region)
    except ValueError as exc:                     # unknown region
        raise HTTPException(422, str(exc)) from exc


@router.get("/meta")
def meta() -> dict[str, Any]:
    return svc.meta()


@router.get("/history/assessments")
def history_assessments(limit: int = 200):
    return svc.history_assessments(max(1, min(limit, 1000)))


@router.get("/history/suggestions")
def history_suggestions(limit: int = 200):
    return svc.history_suggestions(max(1, min(limit, 1000)))


@router.get("/history/runs")
def history_runs(limit: int = 200):
    return svc.history_runs(max(1, min(limit, 1000)))


def register(app: FastAPI) -> None:
    app.include_router(router)
