"""Telemetry history, time-range queries, replay snapshots and exports."""
from __future__ import annotations

import csv
import io
import json
from datetime import datetime

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Anomaly, Sensor, Telemetry
from app.schemas.equipment import Page
from app.schemas.operations import TelemetryRead
from app.services.telemetry_service import load_wide, resample_series, time_bounds

router = APIRouter(prefix="/telemetry", tags=["telemetry"])


def _filtered(stmt, facility_id, sensor_id, sensor_type, start, end):
    if facility_id or sensor_type:
        stmt = stmt.join(Sensor, Sensor.id == Telemetry.sensor_id)
        if facility_id:
            stmt = stmt.where(Sensor.facility_id == facility_id)
        if sensor_type:
            stmt = stmt.where(Sensor.sensor_type == sensor_type)
    if sensor_id:
        stmt = stmt.where(Telemetry.sensor_id == sensor_id)
    if start:
        stmt = stmt.where(Telemetry.timestamp >= start)
    if end:
        stmt = stmt.where(Telemetry.timestamp <= end)
    return stmt


@router.get("", response_model=Page[TelemetryRead])
def list_telemetry(facility_id: str | None = None, sensor_id: str | None = None, sensor_type: str | None = None,
                   start: datetime | None = None, end: datetime | None = None,
                   skip: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=5000), db: Session = Depends(get_db)):
    if start and end and start > end:
        raise HTTPException(422, "start must be before end")
    stmt = _filtered(select(Telemetry), facility_id, sensor_id, sensor_type, start, end)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    items = db.scalars(stmt.order_by(Telemetry.timestamp, Telemetry.sensor_id).offset(skip).limit(limit)).all()
    return {"items": items, "total": total, "skip": skip, "limit": limit}


@router.get("/range")
def telemetry_range(facility_id: str | None = None, db: Session = Depends(get_db)):
    lo, hi = time_bounds(db, facility_id)
    count = db.scalar(_filtered(select(func.count(Telemetry.id)), facility_id, None, None, None, None))
    return {"start": lo, "end": hi, "records": count, "simulated": True,
            "note": "All telemetry is synthetic (simulated). No physical hardware is connected."}


@router.get("/series")
def telemetry_series(facility_id: str, sensor_ids: str | None = None, sensor_type: str | None = None,
                     start: datetime | None = None, end: datetime | None = None,
                     max_points: int = Query(300, ge=10, le=5000), db: Session = Depends(get_db)):
    ids = [s for s in (sensor_ids or "").split(",") if s]
    if sensor_type and not ids:
        ids = db.scalars(select(Sensor.id).where(Sensor.facility_id == facility_id,
                                                 Sensor.sensor_type == sensor_type).order_by(Sensor.id)).all()
    ts, data = load_wide(db, facility_id, start, end, ids or None)
    sensors = {s.id: {"tag": s.tag, "name": s.name, "unit": s.unit, "sensor_type": s.sensor_type,
                      "equipment_id": s.equipment_id, "min_range": s.min_range, "max_range": s.max_range}
               for s in db.scalars(select(Sensor).where(Sensor.id.in_(list(data.keys())))).all()}
    series = {}
    out_ts: list = []
    for sid, vals in data.items():
        out_ts, series[sid] = resample_series(ts, vals, max_points)
    return {"timestamps": [t.isoformat() for t in out_ts], "series": series, "sensors": sensors, "simulated": True}


@router.get("/snapshot")
def telemetry_snapshot(facility_id: str, at: datetime | None = None, db: Session = Depends(get_db)):
    """Readings of every sensor at the latest timestamp <= ``at`` (replay cursor)."""
    lo, hi = time_bounds(db, facility_id)
    if lo is None:
        return {"timestamp": None, "readings": [], "start": None, "end": None}
    at = min(max(at or hi, lo), hi)
    ts = db.scalar(select(func.max(Telemetry.timestamp)).join(Sensor, Sensor.id == Telemetry.sensor_id)
                   .where(Sensor.facility_id == facility_id, Telemetry.timestamp <= at))
    rows = db.execute(select(Telemetry, Sensor).join(Sensor, Sensor.id == Telemetry.sensor_id)
                      .where(Sensor.facility_id == facility_id, Telemetry.timestamp == ts)
                      .order_by(Sensor.id)).all()
    faults = db.scalars(select(Anomaly).where(
        Anomaly.facility_id == facility_id, Anomaly.anomaly_type == "SENSOR_FAULT", Anomaly.source == "TELEMETRY_SCAN",
        and_(Anomaly.start_time <= ts, Anomaly.end_time >= ts))).all()
    suspect = {a.sensor_id: a for a in faults}
    readings = []
    for tel, s in rows:
        if tel.value is None:
            quality, reason = "BAD", "Missing reading"
        elif tel.value < s.min_range or tel.value > s.max_range:
            quality, reason = "BAD", f"Outside range {s.min_range}-{s.max_range} {s.unit}"
        elif s.id in suspect:
            quality, reason = "SUSPECT", f"{suspect[s.id].detection_rule} ({suspect[s.id].id})"
        else:
            quality, reason = "GOOD", ""
        readings.append({"sensor_id": s.id, "tag": s.tag, "name": s.name, "sensor_type": s.sensor_type,
                         "unit": s.unit, "equipment_type": s.equipment_type, "equipment_id": s.equipment_id,
                         "measurement_point": s.measurement_point, "value": tel.value,
                         "derived_value": tel.derived_value, "derived_unit": tel.derived_unit,
                         "min_range": s.min_range, "max_range": s.max_range, "quality": quality, "reason": reason})
    return {"timestamp": ts, "start": lo, "end": hi, "readings": readings, "simulated": True}


@router.get("/export")
def export_telemetry(facility_id: str | None = None, sensor_id: str | None = None, sensor_type: str | None = None,
                     start: datetime | None = None, end: datetime | None = None,
                     format: str = Query("csv", pattern="^(csv|json)$"), limit: int = Query(200000, le=200000),
                     db: Session = Depends(get_db)):
    stmt = _filtered(select(Telemetry), facility_id, sensor_id, sensor_type, start, end)
    rows = db.scalars(stmt.order_by(Telemetry.sensor_id, Telemetry.timestamp).limit(limit)).all()
    fields = ["id", "sensor_id", "timestamp", "value", "derived_value", "derived_unit", "source"]
    recs = [{f: (getattr(r, f).isoformat() if f == "timestamp" else getattr(r, f)) for f in fields} for r in rows]
    name = f"telemetry_{facility_id or 'all'}"
    if format == "json":
        return StreamingResponse(io.BytesIO(json.dumps(recs).encode()), media_type="application/json",
                                 headers={"Content-Disposition": f'attachment; filename="{name}.json"'})
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=fields, lineterminator="\n")
    w.writeheader()
    w.writerows(recs)
    return StreamingResponse(io.BytesIO(buf.getvalue().encode()), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="{name}.csv"'})


def facility_hourly(db: Session, facility_id: str, max_points: int = 160) -> dict:
    """Facility-level trends: total supply inflow, demand outflow, mean pump discharge pressure."""
    sensors = db.scalars(select(Sensor).where(Sensor.facility_id == facility_id)).all()
    ts, data = load_wide(db, facility_id)
    if not ts:
        return {"timestamps": [], "inflow": [], "outflow": [], "discharge_pressure": [], "suction_pressure": []}

    def agg(pred, how="sum"):
        cols = [np.where((data[s.id] < s.min_range) | (data[s.id] > s.max_range), np.nan, data[s.id])
                for s in sensors if pred(s) and s.id in data]
        if not cols:
            return np.full(len(ts), np.nan)
        m = np.vstack(cols)
        # ignore out-of-range values from faulty instruments in aggregates
        return np.nansum(m, axis=0) if how == "sum" else np.nanmean(m, axis=0)

    inflow = agg(lambda s: s.equipment_type == "VALVE" and s.sensor_type == "FLOW" and s.measurement_point == "INLET")
    outflow = agg(lambda s: s.equipment_type == "VALVE" and s.sensor_type == "FLOW" and s.measurement_point == "OUTLET")
    with np.errstate(all="ignore"):
        pd_ = agg(lambda s: s.sensor_type == "PRESSURE" and s.measurement_point == "DISCHARGE", "mean")
        ps_ = agg(lambda s: s.sensor_type == "PRESSURE" and s.measurement_point == "SUCTION", "mean")
    t1, a = resample_series(ts, inflow, max_points)
    _, b = resample_series(ts, outflow, max_points)
    _, c = resample_series(ts, pd_, max_points)
    _, d = resample_series(ts, ps_, max_points)
    return {"timestamps": [t.isoformat() for t in t1], "inflow": a, "outflow": b, "discharge_pressure": c,
            "suction_pressure": d}
