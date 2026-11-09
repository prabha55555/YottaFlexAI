"""FastAPI application entry point.

Run:  uvicorn app.main:app --reload --port 8000   (from the backend/ folder)
Docs: http://localhost:8000/docs
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import func, select

from app.api import equipment, insights, operations, telemetry
from app.config import CORS_ORIGINS
from app.database import SessionLocal, init_db
from app.models import Facility, Telemetry
from app.services.evaluation_service import active_dataset

@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(
    lifespan=lifespan,
    title="YottaFlex Industrial Process Monitoring API",
    version="1.0.0",
    description="Simulated industrial process monitoring: topology, telemetry, mass balance, rule-based anomaly "
                "detection, simulation studio, alarm management and evaluation. All telemetry is synthetic.",
)
app.add_middleware(CORSMiddleware, allow_origins=CORS_ORIGINS, allow_credentials=False,
                   allow_methods=["*"], allow_headers=["*"])


@app.exception_handler(RequestValidationError)
async def validation_handler(_: Request, exc: RequestValidationError):
    errors = [{"field": ".".join(str(p) for p in e["loc"] if p != "body"), "message": e["msg"]} for e in exc.errors()]
    return JSONResponse(status_code=422, content={"detail": {"error": "VALIDATION_ERROR",
                                                             "message": "; ".join(f"{e['field']}: {e['message']}"
                                                                                  for e in errors),
                                                             "errors": errors}})


@app.get("/api/health", tags=["system"])
def health():
    with SessionLocal() as db:
        facilities = db.scalar(select(func.count(Facility.id)))
        telemetry_rows = db.scalar(select(func.count(Telemetry.id)))
    return {"status": "ok", "database": "connected", "facilities": facilities, "telemetry_records": telemetry_rows,
            "dataset": active_dataset(), "simulated_data": True}


for r in (equipment.router, telemetry.router, operations.router, insights.router):
    app.include_router(r, prefix="/api")
