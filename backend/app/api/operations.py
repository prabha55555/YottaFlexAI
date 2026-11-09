"""Topology, mass balance, anomalies, alarms and simulation endpoints."""
from __future__ import annotations

import csv
import io
import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.config import MASS_BALANCE_TOLERANCE_PCT
from app.database import get_db
from app.models import Alarm, Anomaly, Facility, SimulationRun
from app.schemas.equipment import Page
from app.schemas.operations import (
    AlarmAction, AlarmDetail, AlarmRead, AnomalyRead, SimulationDetail, SimulationListItem, SimulationRequest,
)
from app.services import alarm_service
from app.services.anomaly_service import scan_all, scan_facility
from app.services.mass_balance import facility_balance
from app.services.telemetry_service import infer_step_minutes, load_wide
from app.simulation.process_model import build_process_model, snapshot_from_db
from app.simulation.runner import SimulationValidationError, compare_runs, run_simulation
from app.simulation.scenarios import PARAMETER_KEYS, SCENARIOS, preset_parameters
from app.topology.graph import facility_topology

router = APIRouter()


def _facility_or_404(db: Session, facility_id: str) -> Facility:
    fac = db.get(Facility, facility_id)
    if not fac:
        raise HTTPException(404, f"Facility {facility_id} not found")
    return fac


def _stream(rows: list[dict], name: str, fmt: str) -> StreamingResponse:
    if fmt == "json":
        return StreamingResponse(io.BytesIO(json.dumps(rows, default=str, indent=1).encode()),
                                 media_type="application/json",
                                 headers={"Content-Disposition": f'attachment; filename="{name}.json"'})
    buf = io.StringIO()
    fields = list(rows[0].keys()) if rows else ["empty"]
    w = csv.DictWriter(buf, fieldnames=fields, lineterminator="\n", extrasaction="ignore")
    w.writeheader()
    for r in rows:
        w.writerow({k: (json.dumps(v) if isinstance(v, (dict, list)) else v) for k, v in r.items()})
    return StreamingResponse(io.BytesIO(buf.getvalue().encode()), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="{name}.csv"'})


# ----------------------------------------------------------------- topology
@router.get("/topology/{facility_id}", tags=["topology"])
def get_topology(facility_id: str, include_simulation_alarms: bool = False, db: Session = Depends(get_db)):
    _facility_or_404(db, facility_id)
    return facility_topology(db, facility_id, include_simulation_alarms)


# ------------------------------------------------------------- mass balance
@router.get("/mass-balance", tags=["mass-balance"])
def mass_balance(facility_id: str, start: datetime | None = None, end: datetime | None = None,
                 tolerance_pct: float = Query(MASS_BALANCE_TOLERANCE_PCT, gt=0, le=50),
                 window_hours: float | None = Query(None, gt=0), db: Session = Depends(get_db)):
    _facility_or_404(db, facility_id)
    model = build_process_model(snapshot_from_db(db, facility_id))
    ts, readings = load_wide(db, facility_id, start, end)
    if not ts:
        raise HTTPException(404, "No telemetry in the selected range")
    step = infer_step_minutes(ts)
    # sensors already flagged as faulty by the telemetry scan inside the range
    fault_q = select(Anomaly.sensor_id).where(Anomaly.facility_id == facility_id, Anomaly.category == "SENSOR",
                                              Anomaly.source == "TELEMETRY_SCAN", Anomaly.sensor_id.is_not(None),
                                              Anomaly.end_time >= ts[0], Anomaly.start_time <= ts[-1])
    faulty = set(db.scalars(fault_q).all())
    overall = facility_balance(model, readings, step, 0, len(ts), tolerance_pct, sensor_fault_sensors=faulty)
    windows = []
    if window_hours:
        win = max(int(window_hours * 60 / step), 1)
        for s in range(0, len(ts), win):
            e = min(s + win, len(ts))
            fq = select(Anomaly.sensor_id).where(Anomaly.facility_id == facility_id, Anomaly.category == "SENSOR",
                                                 Anomaly.source == "TELEMETRY_SCAN", Anomaly.end_time >= ts[s],
                                                 Anomaly.start_time <= ts[e - 1])
            mb = facility_balance(model, readings, step, s, e, tolerance_pct,
                                  sensor_fault_sensors=set(db.scalars(fq).all()) - {None})
            windows.append({k: mb[k] for k in ("total_inflow_m3", "total_outflow_m3", "storage_change_m3",
                                               "residual_m3", "estimated_leakage_m3", "balance_error_pct", "status",
                                               "classification", "suspect_sensors")}
                           | {"start": ts[s].isoformat(), "end": ts[e - 1].isoformat()})
    overall.update({"start": ts[0].isoformat(), "end": ts[-1].isoformat(), "windows": windows,
                    "exceptions": [w for w in windows if w["status"] == "EXCEPTION"]})
    return overall


# --------------------------------------------------------------- anomalies
def _anomaly_query(facility_id, anomaly_type, severity, category, source, simulation_id, equipment_id, start, end):
    stmt = select(Anomaly)
    if facility_id:
        stmt = stmt.where(Anomaly.facility_id == facility_id)
    if anomaly_type:
        stmt = stmt.where(Anomaly.anomaly_type == anomaly_type)
    if severity:
        stmt = stmt.where(Anomaly.severity == severity)
    if category:
        stmt = stmt.where(Anomaly.category == category)
    if source:
        stmt = stmt.where(Anomaly.source == source)
    if simulation_id:
        stmt = stmt.where(Anomaly.simulation_id == simulation_id)
    if equipment_id:
        stmt = stmt.where((Anomaly.equipment_id == equipment_id) | (Anomaly.sensor_id == equipment_id))
    if start:
        stmt = stmt.where(Anomaly.end_time >= start)
    if end:
        stmt = stmt.where(Anomaly.start_time <= end)
    return stmt


@router.get("/anomalies", response_model=Page[AnomalyRead], tags=["anomalies"])
def list_anomalies(facility_id: str | None = None, anomaly_type: str | None = None, severity: str | None = None,
                   category: str | None = None, source: str | None = None, simulation_id: str | None = None,
                   equipment_id: str | None = None, start: datetime | None = None, end: datetime | None = None,
                   skip: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=1000), db: Session = Depends(get_db)):
    stmt = _anomaly_query(facility_id, anomaly_type, severity, category, source, simulation_id, equipment_id, start, end)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    items = db.scalars(stmt.order_by(Anomaly.detected_at.desc(), Anomaly.id.desc()).offset(skip).limit(limit)).all()
    return {"items": items, "total": total, "skip": skip, "limit": limit}


@router.get("/anomalies/stats", tags=["anomalies"])
def anomaly_stats(facility_id: str | None = None, source: str | None = "TELEMETRY_SCAN", db: Session = Depends(get_db)):
    def grouped(col):
        stmt = select(col, func.count(Anomaly.id))
        if facility_id:
            stmt = stmt.where(Anomaly.facility_id == facility_id)
        if source:
            stmt = stmt.where(Anomaly.source == source)
        return {k: v for k, v in db.execute(stmt.group_by(col)).all()}

    return {"by_type": grouped(Anomaly.anomaly_type), "by_severity": grouped(Anomaly.severity),
            "by_category": grouped(Anomaly.category), "by_rule": grouped(Anomaly.detection_rule),
            "by_facility": grouped(Anomaly.facility_id)}


@router.get("/anomalies/export", tags=["anomalies"])
def export_anomalies(facility_id: str | None = None, anomaly_type: str | None = None, severity: str | None = None,
                     source: str | None = None, simulation_id: str | None = None,
                     format: str = Query("csv", pattern="^(csv|json)$"), db: Session = Depends(get_db)):
    stmt = _anomaly_query(facility_id, anomaly_type, severity, None, source, simulation_id, None, None, None)
    rows = [AnomalyRead.model_validate(a).model_dump(mode="json")
            for a in db.scalars(stmt.order_by(Anomaly.id)).all()]
    return _stream(rows, "anomalies", format)


@router.get("/anomalies/{anomaly_id}", response_model=AnomalyRead, tags=["anomalies"])
def get_anomaly(anomaly_id: str, db: Session = Depends(get_db)):
    a = db.get(Anomaly, anomaly_id)
    if not a:
        raise HTTPException(404, f"Anomaly {anomaly_id} not found")
    return a


@router.post("/anomalies/scan", tags=["anomalies"])
def scan(facility_id: str | None = None, tolerance_pct: float | None = Query(None, gt=0, le=50),
         db: Session = Depends(get_db)):
    """Run rule-based detection over stored telemetry (idempotent)."""
    if facility_id:
        _facility_or_404(db, facility_id)
        det, created, info = scan_facility(db, facility_id, tolerance_pct=tolerance_pct)
        return {facility_id: {"detected": len(det.anomalies) if det else 0, "new": len(created), **info}}
    return scan_all(db)


# ------------------------------------------------------------------ alarms
def _alarm_query(status, severity, facility_id, equipment_id, simulation_id, source, alarm_type):
    stmt = select(Alarm)
    if status:
        stmt = stmt.where(Alarm.status.in_(status.split(",")))
    if severity:
        stmt = stmt.where(Alarm.severity.in_(severity.split(",")))
    if facility_id:
        stmt = stmt.where(Alarm.facility_id == facility_id)
    if equipment_id:
        stmt = stmt.where(Alarm.equipment_id == equipment_id)
    if simulation_id:
        stmt = stmt.where(Alarm.simulation_id == simulation_id)
    if alarm_type:
        stmt = stmt.where(Alarm.alarm_type == alarm_type)
    if source == "LIVE":
        stmt = stmt.where(Alarm.simulation_id.is_(None))
    elif source == "SIMULATION":
        stmt = stmt.where(Alarm.simulation_id.is_not(None))
    return stmt


@router.get("/alarms", response_model=Page[AlarmRead], tags=["alarms"])
def list_alarms(status: str | None = None, severity: str | None = None, facility_id: str | None = None,
                equipment_id: str | None = None, simulation_id: str | None = None,
                source: str | None = Query(None, pattern="^(LIVE|SIMULATION)$"), alarm_type: str | None = None,
                skip: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=1000), db: Session = Depends(get_db)):
    stmt = _alarm_query(status, severity, facility_id, equipment_id, simulation_id, source, alarm_type)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    sev_order = func.instr("LOWMEDIUMHIGHCRITICAL", Alarm.severity)
    items = db.scalars(stmt.order_by(sev_order.desc(), Alarm.raised_at.desc(), Alarm.id.desc())
                       .offset(skip).limit(limit)).all()
    return {"items": items, "total": total, "skip": skip, "limit": limit}


@router.get("/alarms/stats", tags=["alarms"])
def alarm_stats(facility_id: str | None = None, source: str | None = Query("LIVE", pattern="^(LIVE|SIMULATION)$"),
                db: Session = Depends(get_db)):
    base = _alarm_query(None, None, facility_id, None, None, source, None).subquery()
    by_status = dict(db.execute(select(base.c.status, func.count()).group_by(base.c.status)).all())
    by_sev = dict(db.execute(select(base.c.severity, func.count())
                             .where(base.c.status.in_(("ACTIVE", "ACKNOWLEDGED"))).group_by(base.c.severity)).all())
    return {"by_status": by_status, "open_by_severity": by_sev}


@router.get("/alarms/export", tags=["alarms"])
def export_alarms(status: str | None = None, facility_id: str | None = None,
                  source: str | None = Query(None, pattern="^(LIVE|SIMULATION)$"),
                  format: str = Query("csv", pattern="^(csv|json)$"), db: Session = Depends(get_db)):
    stmt = _alarm_query(status, None, facility_id, None, None, source, None)
    rows = [AlarmRead.model_validate(a).model_dump(mode="json") for a in db.scalars(stmt.order_by(Alarm.id)).all()]
    return _stream(rows, "alarms", format)


@router.get("/alarms/{alarm_id}", response_model=AlarmDetail, tags=["alarms"])
def get_alarm(alarm_id: str, db: Session = Depends(get_db)):
    a = db.scalar(select(Alarm).options(selectinload(Alarm.events)).where(Alarm.id == alarm_id))
    if not a:
        raise HTTPException(404, f"Alarm {alarm_id} not found")
    detail = AlarmDetail.model_validate(a)
    if a.anomaly_id:
        an = db.get(Anomaly, a.anomaly_id)
        detail.anomaly = AnomalyRead.model_validate(an) if an else None
    return detail


def _action(action: str):
    def handler(alarm_id: str, body: AlarmAction, db: Session = Depends(get_db)):
        a = db.get(Alarm, alarm_id)
        if not a:
            raise HTTPException(404, f"Alarm {alarm_id} not found")
        alarm_service.transition(db, a, action, body.actor, body.note)
        return get_alarm(alarm_id, db)
    handler.__name__ = f"{action}_alarm"
    return handler


for _act in ("acknowledge", "resolve", "close"):
    router.add_api_route(f"/alarms/{{alarm_id}}/{_act}", _action(_act), methods=["POST"],
                         response_model=AlarmDetail, tags=["alarms"], name=f"{_act}_alarm")


# -------------------------------------------------------------- simulations
@router.get("/simulations/scenarios", tags=["simulations"])
def scenarios(facility_id: str | None = None, db: Session = Depends(get_db)):
    presets = {}
    if facility_id:
        _facility_or_404(db, facility_id)
        model = build_process_model(snapshot_from_db(db, facility_id))
        presets = {s: preset_parameters(model, s) for s in SCENARIOS}
    return {"scenarios": [{"id": k, "description": v, "preset": presets.get(k)} for k, v in SCENARIOS.items()],
            "parameters": list(PARAMETER_KEYS)}


@router.post("/simulations", response_model=SimulationDetail, status_code=201, tags=["simulations"])
def create_simulation(body: SimulationRequest, db: Session = Depends(get_db)):
    _facility_or_404(db, body.facility_id)
    params = body.parameters.model_dump(exclude_none=True)
    try:
        run = run_simulation(db, body.facility_id, body.scenario, params, seed=body.seed, steps=body.steps,
                             step_minutes=body.step_minutes, fault_start_step=body.fault_start_step, name=body.name,
                             baseline_simulation_id=body.baseline_simulation_id, run_baseline=body.run_baseline,
                             apply_preset=body.apply_preset)
    except SimulationValidationError as exc:
        raise HTTPException(422, {"error": "SIMULATION_VALIDATION_FAILED", "simulation_id": exc.run.id,
                                  "message": "Simulation inputs are invalid; run recorded as FAILED.",
                                  "errors": exc.run.validation_errors}) from exc
    return run


@router.get("/simulations", response_model=Page[SimulationListItem], tags=["simulations"])
def list_simulations(facility_id: str | None = None, scenario: str | None = None, status: str | None = None,
                     skip: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=500), db: Session = Depends(get_db)):
    stmt = select(SimulationRun)
    if facility_id:
        stmt = stmt.where(SimulationRun.facility_id == facility_id)
    if scenario:
        stmt = stmt.where(SimulationRun.scenario == scenario)
    if status:
        stmt = stmt.where(SimulationRun.status == status)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    items = db.scalars(stmt.order_by(SimulationRun.created_at.desc(), SimulationRun.id.desc())
                       .offset(skip).limit(limit)).all()
    return {"items": items, "total": total, "skip": skip, "limit": limit}


@router.get("/simulations/compare", tags=["simulations"])
def compare(baseline_id: str, modified_id: str, db: Session = Depends(get_db)):
    a, b = db.get(SimulationRun, baseline_id), db.get(SimulationRun, modified_id)
    if not a or not b:
        raise HTTPException(404, "Both simulation runs must exist")
    if a.status != "COMPLETED" or b.status != "COMPLETED":
        raise HTTPException(422, "Only COMPLETED runs can be compared")
    out = compare_runs(a, b)
    n = min(a.steps, b.steps)
    out["timeseries"] = {"timestamps": a.timeseries["timestamps"][:n],
                         "baseline": a.timeseries, "modified": b.timeseries, "length": n}
    return out


@router.get("/simulations/{sim_id}", response_model=SimulationDetail, tags=["simulations"])
def get_simulation(sim_id: str, db: Session = Depends(get_db)):
    r = db.get(SimulationRun, sim_id)
    if not r:
        raise HTTPException(404, f"Simulation {sim_id} not found")
    return r


@router.get("/simulations/{sim_id}/export", tags=["simulations"])
def export_simulation(sim_id: str, format: str = Query("json", pattern="^(csv|json)$"),
                      content: str = Query("timeseries", pattern="^(timeseries|readings|full)$"),
                      db: Session = Depends(get_db)):
    r = get_simulation(sim_id, db)
    if format == "json":
        doc = SimulationDetail.model_validate(r).model_dump(mode="json")
        doc["readings"] = r.readings
        doc["anomalies"] = [AnomalyRead.model_validate(a).model_dump(mode="json") for a in
                            db.scalars(select(Anomaly).where(Anomaly.simulation_id == sim_id).order_by(Anomaly.id))]
        return StreamingResponse(io.BytesIO(json.dumps(doc, indent=1).encode()), media_type="application/json",
                                 headers={"Content-Disposition": f'attachment; filename="{sim_id}.json"'})
    if r.status != "COMPLETED":
        raise HTTPException(422, "Failed runs have no time series; export as JSON to see validation errors")
    ts = r.timeseries["timestamps"]
    rows = []
    for i, t in enumerate(ts):
        row = {"simulation_id": sim_id, "step": i, "timestamp": t}
        if content == "readings":
            for sid, vals in sorted((r.readings or {}).items()):
                row[sid] = vals[i]
        else:
            for pid, d in r.timeseries["lines"].items():
                for k, vals in d.items():
                    row[f"{pid}.{k}"] = vals[i]
            for tid, d in r.timeseries["tanks"].items():
                for k, vals in d.items():
                    row[f"{tid}.{k}"] = vals[i]
            for grp in ("inlets", "outlets"):
                for vid, d in r.timeseries[grp].items():
                    for k, vals in d.items():
                        row[f"{vid}.{k}"] = vals[i]
        rows.append(row)
    return _stream(rows, f"{sim_id}_{content}", "csv")
