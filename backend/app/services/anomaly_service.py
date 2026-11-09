"""Run detection against stored telemetry and persist anomalies + alarms.

Scanning is idempotent: each anomaly has a fingerprint (facility, equipment,
sensor, type, rule, start time, source); re-scanning does not duplicate rows.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.anomaly_detection.detector import Detector, DetectionResult
from app.models import Alarm, Anomaly, Facility
from app.services.alarm_service import create_alarm_from_anomaly
from app.services.ids import SequenceAllocator
from app.services.telemetry_service import infer_step_minutes, load_wide
from app.simulation.engine import OperatingSettings
from app.simulation.process_model import build_process_model, snapshot_from_db

ANOMALY_COLUMNS = ("facility_id", "equipment_type", "equipment_id", "sensor_id", "anomaly_type", "category",
                   "severity", "detection_rule", "rule_description", "start_time", "end_time", "detected_at",
                   "observed_value", "expected_value", "threshold", "unit", "evidence", "recommended_action")


def _json_safe(obj):
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    if isinstance(obj, datetime):
        return obj.isoformat()
    if hasattr(obj, "item"):
        return obj.item()
    return obj


def persist_anomalies(db: Session, anomalies: list[dict], source: str, simulation_id: str | None = None,
                      create_alarms: bool = True) -> list[Anomaly]:
    anm_ids = SequenceAllocator(db, Anomaly.id, "ANM", 6)
    alm_ids = SequenceAllocator(db, Alarm.id, "ALM", 6)
    existing = set(db.scalars(select(Anomaly.fingerprint)).all())
    created = []
    for a in anomalies:
        fp = a["fingerprint"] if simulation_id is None else f"{simulation_id}:{a['fingerprint']}"[:64]
        if fp in existing:
            continue
        existing.add(fp)
        row = Anomaly(id=anm_ids(), fingerprint=fp, source=source, simulation_id=simulation_id,
                      **{k: _json_safe(a.get(k)) if k == "evidence" else a.get(k) for k in ANOMALY_COLUMNS})
        db.add(row)
        created.append(row)
        if create_alarms:
            db.flush()
            create_alarm_from_anomaly(db, alm_ids(), a, row.id, simulation_id)
    db.flush()
    return created


def scan_facility(db: Session, facility_id: str, start: datetime | None = None, end: datetime | None = None,
                  tolerance_pct: float | None = None) -> tuple[DetectionResult | None, list[Anomaly], dict]:
    model = build_process_model(snapshot_from_db(db, facility_id))
    timestamps, readings = load_wide(db, facility_id, start, end)
    if not timestamps:
        return None, [], {"timestamps": 0}
    step = infer_step_minutes(timestamps)
    det = Detector(model, OperatingSettings()).detect(readings, timestamps, step,
                                                      balance_window_steps=max(int(24 * 60 / step), 4),
                                                      tolerance_pct=tolerance_pct)
    created = persist_anomalies(db, det.anomalies, "TELEMETRY_SCAN")
    db.commit()
    return det, created, {"timestamps": len(timestamps), "sensors": len(readings), "step_minutes": step}


def scan_all(db: Session) -> dict:
    out = {}
    for fac in db.scalars(select(Facility).order_by(Facility.id)).all():
        det, created, info = scan_facility(db, fac.id)
        out[fac.id] = {"detected": len(det.anomalies) if det else 0, "new": len(created), **info}
    return out
