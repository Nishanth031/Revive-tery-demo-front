"""Thin FastAPI wrapper over pipeline.assess (optional extra: pip install -e ".[api]").

/assess (insight=true adds the `insight` key), /whatif (re-run the economics under overrides), /passport.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ValidationError

from revive_ml import __version__
from revive_ml.contract import Bundle, ContractError, Metadata, validate_telemetry
from revive_ml.pipeline import assess

app = FastAPI(title="revive-tery-ml", version=__version__)


class AssessRequest(BaseModel):
    metadata: dict[str, Any]
    telemetry: list[dict[str, Any]]
    workloads: dict[str, Any] | None = None
    region: str | None = None


class WhatIfRequest(AssessRequest):
    overrides: dict[str, Any] = {}


def _bundle(req: AssessRequest) -> Bundle:
    try:
        meta = Metadata.model_validate(req.metadata)
        df, ignored = validate_telemetry(pd.DataFrame(req.telemetry), meta.asset_id)
    except (ValidationError, ContractError) as exc:
        raise HTTPException(status_code=422, detail=f"contract error: {exc}") from exc
    return Bundle(meta=meta, telemetry=df, ignored_columns=ignored)


def _assess(req: AssessRequest, bundle: Bundle) -> dict[str, Any]:
    try:
        return assess(bundle, req.workloads, region=req.region)
    except ValueError as exc:                       # unknown region
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


@app.post("/assess")
def assess_endpoint(req: AssessRequest, insight: bool = False) -> dict[str, Any]:
    bundle = _bundle(req)
    report = _assess(req, bundle)
    if insight:
        from revive_ml.insight import insight_for
        report = {**report, "insight": insight_for(report, bundle)}
    return report


@app.post("/whatif")
def whatif_endpoint(req: WhatIfRequest) -> dict[str, Any]:
    from revive_ml.insight import break_even, reroute
    bundle = _bundle(req)
    report = _assess(req, bundle)
    out = reroute(report, {**req.overrides, **({"region": req.region} if req.region else {})})
    if out is None:
        return {"decision": report["decision"], "rerouted": False,
                "reason": "the report did not reach the economics stage, so there is nothing to re-route"}
    return {**out, "rerouted": True, "break_even_tariff": break_even(report, "tariff", req.overrides)}


@app.post("/passport")
def passport_endpoint(req: AssessRequest) -> dict[str, Any]:
    from revive_ml.insight import passport
    bundle = _bundle(req)
    return passport(_assess(req, bundle), bundle.meta, bundle.telemetry)
