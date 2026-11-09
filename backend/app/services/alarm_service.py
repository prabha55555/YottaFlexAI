"""Alarm lifecycle:  ACTIVE -> ACKNOWLEDGED -> RESOLVED -> CLOSED.

Every transition is persisted as an immutable AlarmEvent (history/audit trail).
Invalid transitions raise HTTP 409 with an explanation.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import Alarm, AlarmEvent

TRANSITIONS = {
    "acknowledge": ("ACTIVE", "ACKNOWLEDGED"),
    "resolve": ("ACKNOWLEDGED", "RESOLVED"),
    "close": ("RESOLVED", "CLOSED"),
}


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)


def create_alarm_from_anomaly(db: Session, alarm_id: str, anomaly: dict, anomaly_id: str,
                              simulation_id: str | None) -> Alarm:
    a = anomaly
    label = a["anomaly_type"].replace("_", " ").title()
    target = a["equipment_id"] + (f" / {a['sensor_id']}" if a.get("sensor_id") else "")
    obs = a.get("observed_value")
    msg = f"{label} on {target} ({a['detection_rule']})"
    if obs is not None:
        msg += f": observed {obs:g} {a.get('unit', '')}".rstrip()
        if a.get("expected_value") is not None:
            msg += f", expected {a['expected_value']:g} {a.get('unit', '')}".rstrip()
    alarm = Alarm(
        id=alarm_id, facility_id=a["facility_id"], equipment_type=a["equipment_type"],
        equipment_id=a["equipment_id"], anomaly_id=anomaly_id, simulation_id=simulation_id,
        alarm_type=a["anomaly_type"], severity=a["severity"], status="ACTIVE", message=msg,
        recommended_action=a.get("recommended_action", ""), raised_at=a["detected_at"],
    )
    alarm.events.append(AlarmEvent(from_status=None, to_status="ACTIVE", actor="detection-engine",
                                   note=f"Raised by rule {a['detection_rule']}", timestamp=_now()))
    db.add(alarm)
    return alarm


def transition(db: Session, alarm: Alarm, action: str, actor: str, note: str = "") -> Alarm:
    if action not in TRANSITIONS:
        raise HTTPException(status_code=400, detail=f"Unknown action '{action}'")
    required, target = TRANSITIONS[action]
    if alarm.status != required:
        raise HTTPException(status_code=409, detail={
            "error": "INVALID_TRANSITION",
            "message": f"Cannot {action} alarm {alarm.id}: status is {alarm.status}, expected {required}. "
                       f"Lifecycle is ACTIVE -> ACKNOWLEDGED -> RESOLVED -> CLOSED."})
    now = _now()
    prev = alarm.status
    alarm.status = target
    if target == "ACKNOWLEDGED":
        alarm.acknowledged_at, alarm.acknowledged_by = now, actor
    elif target == "RESOLVED":
        alarm.resolved_at, alarm.resolved_by = now, actor
    elif target == "CLOSED":
        alarm.closed_at, alarm.closed_by = now, actor
    alarm.events.append(AlarmEvent(from_status=prev, to_status=target, actor=actor, note=note, timestamp=now))
    db.commit()
    db.refresh(alarm)
    return alarm
