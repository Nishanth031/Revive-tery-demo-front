"""/api/intelligence/*: the ML-led workflow (understand uploads, store them, assess, advise a second use).

Additive: registered from main.py with two lines; no existing route or model is changed.
"""
from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, FastAPI, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .schemas import SpecIn
from .services import ingest
from .services import intelligence as svc

router = APIRouter(prefix="/api/intelligence", tags=["intelligence"])


class AdviseIn(BaseModel):
    battery_id: str = Field(min_length=1)
    spec: SpecIn | None = None          # needed only for an upload whose spec the ML could not establish
    brand: str | None = None
    workloads: dict[str, Any] | None = None


def _hints(chemistry, brand, series_cells, parallel_cells, rated_capacity_ah, nominal_voltage_v) -> dict[str, Any]:
    try:
        return svc.hints_from_form(chemistry, brand, series_cells, parallel_cells, rated_capacity_ah, nominal_voltage_v)
    except ValueError as exc:
        from fastapi import HTTPException
        raise HTTPException(422, str(exc)) from exc


@router.post("/map", summary="Dry run: how would the ML read these files? Nothing is stored.")
def map_upload(files: Annotated[list[UploadFile], File(description=".csv, .xlsx or .zip")],
               chemistry: Annotated[str | None, Form()] = None, brand: Annotated[str | None, Form()] = None,
               series_cells: Annotated[str | None, Form()] = None, parallel_cells: Annotated[str | None, Form()] = None,
               rated_capacity_ah: Annotated[str | None, Form()] = None,
               nominal_voltage_v: Annotated[str | None, Form()] = None):
    h = _hints(chemistry, brand, series_cells, parallel_cells, rated_capacity_ah, nominal_voltage_v)
    return svc.analyze([(f.filename or "upload", f.file) for f in files], "synthetic", h, store=False)


@router.post("/analyze", status_code=201,
             summary="Understand the files, store them in the database, assess each battery and advise a second use.")
def analyze(files: Annotated[list[UploadFile], File(description=".csv, .xlsx or .zip")],
            data_provenance: Annotated[str, Form()] = "synthetic",
            chemistry: Annotated[str | None, Form()] = None, brand: Annotated[str | None, Form()] = None,
            series_cells: Annotated[str | None, Form()] = None, parallel_cells: Annotated[str | None, Form()] = None,
            rated_capacity_ah: Annotated[str | None, Form()] = None,
            nominal_voltage_v: Annotated[str | None, Form()] = None,
            assess_after: Annotated[bool, Form()] = True):
    """Say honestly what the data is (measured, simulated or synthetic). Anything the ML cannot establish
    (a pack's series count, an ambiguous maker's chemistry) comes back under `needs_from_user`, not guessed."""
    h = _hints(chemistry, brand, series_cells, parallel_cells, rated_capacity_ah, nominal_voltage_v)
    return svc.analyze([(f.filename or "upload", f.file) for f in files], data_provenance, h, True, assess_after)


@router.post("/advise", status_code=201, summary="Assess a stored battery and rank its second-use options.")
def advise_one(req: AdviseIn):
    return svc.advise_battery(req.battery_id, req.spec, req.workloads, req.brand)


@router.get("/suggestions", summary="Saved second-use suggestions, newest first.")
def suggestions(battery_id: str | None = None, limit: int = 100):
    return svc.list_suggestions(battery_id, max(1, min(limit, 500)))


@router.get("/profiles", summary="Chemistry and maker characteristics the advisor uses (assumed priors).")
def profiles():
    return svc.profiles_catalog()


def register(app: FastAPI) -> None:
    """Mount the routes and the error mapping for this workflow."""
    from revive_ml.intelligence.workflow import UploadError

    @app.exception_handler(svc.NeedsInput)
    async def _needs(_: Request, exc: svc.NeedsInput):
        return JSONResponse(status_code=422, content={"detail": str(exc), "code": "needs_input",
                                                      "battery_id": exc.battery_id, "needs": exc.needs})

    @app.exception_handler(UploadError)
    async def _unreadable(_: Request, exc: UploadError):
        return JSONResponse(status_code=422, content={"detail": str(exc), "code": "unreadable_upload"})

    app.include_router(router)
