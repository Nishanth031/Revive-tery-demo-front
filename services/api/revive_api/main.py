"""REVIVE-TERY backend API (FastAPI). Local only: bind it to 127.0.0.1.

Run (from the backend folder):  python -m uvicorn revive_api.main:app --host 127.0.0.1 --port 8000
Interactive docs:               http://127.0.0.1:8000/docs
"""
from __future__ import annotations

import asyncio
import json
import shutil
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from . import db, settings
from .schemas import AssessIn, FaultIn, RunStartIn
from .services import assess, batteries, ingest, runs
from bms_engine import DatabaseUnavailable
from ml_analyzer_suggester import IngestionError
from revive_ml import __version__ as ml_version

API_VERSION = "0.1.0"


@asynccontextmanager
async def lifespan(_: FastAPI):
    try:
        db.ensure_tables()          # additive: ml_telemetry, ml_ingest_log, assessments
    except DatabaseUnavailable:
        pass                        # /api/health reports it; endpoints answer 503 until the database exists
    yield


app = FastAPI(title="REVIVE-TERY API", version=API_VERSION, lifespan=lifespan,
              description="Database, BMS engine, hardware/simulated test runs and the ML engine behind one local API.")
app.add_middleware(CORSMiddleware, allow_origins=settings.CORS_ORIGINS, allow_methods=["*"], allow_headers=["*"],
                   # the web studio can be served from any local port (python -m http.server 8080/8090/...); local only
                   allow_origin_regex=r"^http://(localhost|127\.0\.0\.1)(:\d+)?$")


# --- errors -----------------------------------------------------------------------------
@app.exception_handler(DatabaseUnavailable)
async def _db_down(_: Request, exc: DatabaseUnavailable):
    return JSONResponse(status_code=503, content={"detail": str(exc), "code": "database_unavailable"})


@app.exception_handler(batteries.NotFound)
async def _not_found(_: Request, exc: batteries.NotFound):
    return JSONResponse(status_code=404, content={"detail": str(exc), "code": "not_found"})


@app.exception_handler(assess.AdapterError)
async def _adapter(_: Request, exc: assess.AdapterError):
    return JSONResponse(status_code=422, content={"detail": str(exc), "code": "cannot_assess"})


@app.exception_handler(IngestionError)
async def _ingestion(_: Request, exc: IngestionError):
    return JSONResponse(status_code=422, content={"detail": str(exc), "code": "ingestion_failed"})


@app.exception_handler(ingest.UploadTooLarge)
async def _too_large(_: Request, exc: ingest.UploadTooLarge):
    return JSONResponse(status_code=413, content={"detail": str(exc), "code": "too_large"})


@app.exception_handler(runs.RunConflict)
async def _conflict(_: Request, exc: runs.RunConflict):
    return JSONResponse(status_code=409, content={"detail": str(exc), "code": "run_conflict"})


api = APIRouter(prefix="/api")


# --- health -----------------------------------------------------------------------------
@api.get("/health", tags=["system"])
def health():
    try:
        tables = db.table_names()
        database = {"available": True, "tables": tables}
    except DatabaseUnavailable as exc:
        database = {"available": False, "error": str(exc)}
    return {"status": "ok", "api_version": API_VERSION, "ml_engine_version": ml_version,
            "database": {"path": str(settings.DB_PATH), **database},
            "run": {"status": runs.controller.status}}


# --- batteries --------------------------------------------------------------------------
@api.get("/batteries", tags=["batteries"])
def list_batteries():
    return batteries.list_batteries()


@api.get("/batteries/{battery_id}", tags=["batteries"])
def battery_detail(battery_id: str):
    return batteries.detail(battery_id)


# --- test runs --------------------------------------------------------------------------
@api.get("/ports", tags=["runs"])
def list_ports():
    return runs.ports()


@api.get("/faults", tags=["runs"])
def list_faults():
    return runs.faults()


@api.post("/runs", tags=["runs"], status_code=201)
def start_run(req: RunStartIn):
    return runs.start(req)


@api.post("/runs/stop", tags=["runs"])
def stop_run():
    return runs.stop()


@api.post("/runs/fault", tags=["runs"])
def inject_fault(req: FaultIn):
    runs.set_fault(req.fault)
    return {"fault": req.fault}


@api.get("/runs/current", tags=["runs"])
def current_run(tail: int = 600):
    return runs.snapshot_json(tail=max(1, min(tail, 2000)))


@api.get("/runs/stream", tags=["runs"])
async def stream_run(request: Request):
    """Server-sent events: one JSON message per change, readings newer than the last one sent."""

    async def events():
        last_ts: float | None = None
        last_sig = None
        idle = 0
        while not await request.is_disconnected():
            payload = await asyncio.to_thread(runs.snapshot_json, last_ts)
            if payload["readings"]:
                last_ts = payload["readings"][-1]["timestamp"]
            sig = (payload["status"], last_ts, payload["notice"], payload["error"], payload["log_note"],
                   payload["fault"]["last"], payload["stale"])
            if sig != last_sig:
                last_sig, idle = sig, 0
                yield f"event: snapshot\ndata: {json.dumps(payload, default=str)}\n\n"
            else:
                idle += 1
                if idle % 30 == 0:
                    yield ": keep-alive\n\n"
            await asyncio.sleep(0.4)

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# --- uploads ----------------------------------------------------------------------------
@api.post("/uploads", tags=["uploads"], status_code=201)
def upload(files: Annotated[list[UploadFile], File(description=".csv, .xlsx or .zip")],
           data_provenance: Annotated[str, Form()] = "synthetic"):
    """Store uploaded cycler/telemetry files (ml_telemetry). Say honestly what the data is: measured, simulated or synthetic."""
    if data_provenance not in ingest.PROVENANCES:
        raise HTTPException(422, f"data_provenance must be one of {ingest.PROVENANCES}")
    return ingest.ingest([(f.filename or "upload", f.file) for f in files], data_provenance)


@api.get("/uploads", tags=["uploads"])
def uploads_log(limit: int = 100):
    return ingest.ingest_log(max(1, min(limit, 1000)))


# --- ML assessments ---------------------------------------------------------------------
@api.post("/assessments", tags=["assessments"], status_code=201)
def create_assessment(req: AssessIn):
    """Assess a battery. engine=auto uses the full ML engine and falls back to the lite analyzer, saying why."""
    return assess.assess_battery(req)


@api.post("/assessments/bundle", tags=["assessments"], status_code=201)
def assess_bundle(bundle: Annotated[UploadFile, File(description="zip with metadata.json + telemetry.csv|parquet")]):
    """Full ML engine on a data-contract bundle (see revive-tery-ml README)."""
    tmp = Path(tempfile.mkdtemp(prefix="revive_bundle_up_"))
    try:
        paths = ingest.save_uploads([(bundle.filename or "bundle.zip", bundle.file)], tmp)
        return assess.assess_bundle(paths[0])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@api.get("/assessments", tags=["assessments"])
def list_assessments(battery_id: str | None = None, limit: int = 100):
    return assess.list_assessments(battery_id, max(1, min(limit, 500)))


@api.get("/assessments/{assessment_id}", tags=["assessments"])
def get_assessment(assessment_id: str):
    return assess.get_assessment(assessment_id)


app.include_router(api)

from . import routes_intelligence  # noqa: E402  (ML-led workflow: /api/intelligence/*)

routes_intelligence.register(app)

from . import routes_fleet  # noqa: E402  (fleet, battery, what-if, meta, history: /api/fleet ...)

routes_fleet.register(app)
