"""Data integrity and validation checks over the live database.

All counts are computed from the data; nothing is assumed or hard-coded.
"""
from __future__ import annotations

from collections import Counter

import numpy as np
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.models import (
    Alarm,
    AlarmEvent,
    Anomaly,
    Facility,
    OperatingMode,
    Pipe,
    Pump,
    Sensor,
    SimulationRun,
    Tank,
    Telemetry,
    Valve,
)
from app.services.ids import is_valid_id
from app.services.mass_balance import facility_balance
from app.services.telemetry_service import infer_step_minutes, load_wide
from app.simulation.process_model import build_process_model, snapshot_from_db
from app.topology.graph import facility_topology

ID_TABLES = [
    (Facility, "FAC"), (Pump, "PUMP"), (Tank, "TANK"), (Valve, "VALVE"), (Pipe, "PIPE"), (Sensor, "SNS"),
    (OperatingMode, "MODE"), (Anomaly, "ANM"), (Alarm, "ALM"), (SimulationRun, "SIM"),
]


def primary_key_checks(db: Session) -> dict:
    errors = []
    checked = 0
    for model, prefix in ID_TABLES:
        ids = db.scalars(select(model.id)).all()
        checked += len(ids)
        dup = [k for k, c in Counter(ids).items() if c > 1]
        for d in dup:
            errors.append({"table": model.__tablename__, "id": d, "error": "DUPLICATE_PRIMARY_KEY"})
        for i in ids:
            if not is_valid_id(prefix, i):
                errors.append({"table": model.__tablename__, "id": i, "error": "INVALID_ID_FORMAT",
                               "message": f"'{i}' does not match the {prefix} identifier pattern."})
    tel_dup = db.execute(text(
        "SELECT COUNT(*) FROM (SELECT sensor_id, timestamp FROM telemetry GROUP BY sensor_id, timestamp "
        "HAVING COUNT(*) > 1)")).scalar_one()
    return {"checked_records": checked, "error_count": len(errors) + tel_dup, "errors": errors[:200],
            "duplicate_telemetry_keys": tel_dup}


def foreign_key_checks(db: Session) -> dict:
    errors = []
    fac_ids = set(db.scalars(select(Facility.id)).all())
    nodes = {**{i: "PUMP" for i in db.scalars(select(Pump.id))}, **{i: "TANK" for i in db.scalars(select(Tank.id))},
             **{i: "VALVE" for i in db.scalars(select(Valve.id))}}
    node_fac = {}
    for model in (Pump, Tank, Valve, Pipe):
        for i, f in db.execute(select(model.id, model.facility_id)).all():
            node_fac[i] = f
            if f not in fac_ids:
                errors.append({"table": model.__tablename__, "id": i, "field": "facility_id",
                               "message": f"References missing facility {f}."})
    for p in db.scalars(select(Pipe)).all():
        for fld, nid, ntype in (("from_node_id", p.from_node_id, p.from_node_type),
                                ("to_node_id", p.to_node_id, p.to_node_type)):
            if nid not in nodes:
                errors.append({"table": "pipes", "id": p.id, "field": fld,
                               "message": f"Pipe references missing node {nid}."})
            elif nodes[nid] != ntype:
                errors.append({"table": "pipes", "id": p.id, "field": fld,
                               "message": f"Declared type {ntype} but {nid} is a {nodes[nid]}."})
    for s in db.scalars(select(Sensor)).all():
        if s.facility_id not in fac_ids:
            errors.append({"table": "sensors", "id": s.id, "field": "facility_id",
                           "message": f"References missing facility {s.facility_id}."})
        if s.equipment_id not in node_fac:
            errors.append({"table": "sensors", "id": s.id, "field": "equipment_id",
                           "message": f"Sensor references missing equipment {s.equipment_id}."})
        elif node_fac[s.equipment_id] != s.facility_id:
            errors.append({"table": "sensors", "id": s.id, "field": "equipment_id",
                           "message": f"Equipment {s.equipment_id} is in another facility."})
    orphan_tel = db.execute(text(
        "SELECT COUNT(*) FROM telemetry t LEFT JOIN sensors s ON s.id = t.sensor_id WHERE s.id IS NULL")).scalar_one()
    if orphan_tel:
        errors.append({"table": "telemetry", "id": None, "field": "sensor_id",
                       "message": f"{orphan_tel} telemetry rows reference missing sensors."})
    orphan_alarm = db.execute(text(
        "SELECT COUNT(*) FROM alarms a LEFT JOIN anomalies n ON n.id = a.anomaly_id "
        "WHERE a.anomaly_id IS NOT NULL AND n.id IS NULL")).scalar_one()
    if orphan_alarm:
        errors.append({"table": "alarms", "id": None, "field": "anomaly_id",
                       "message": f"{orphan_alarm} alarms reference missing anomalies."})
    sqlite_fk = db.execute(text("PRAGMA foreign_key_check")).all()
    for row in sqlite_fk:
        errors.append({"table": row[0], "id": row[1], "field": row[2], "message": "SQLite foreign_key_check violation"})
    checked = len(node_fac) + db.scalar(select(func.count(Sensor.id))) + db.scalar(select(func.count(Telemetry.id)))
    return {"checked_relationships": int(checked), "error_count": len(errors), "errors": errors[:200]}


def duplicate_checks(db: Session) -> dict:
    out = {}
    # Names must be unique within a facility (the same name may appear in different facilities).
    for model in (Facility, Pump, Tank, Valve, Pipe, Sensor):
        if model is Facility:
            keys = db.scalars(select(model.name)).all()
        else:
            keys = db.execute(select(model.facility_id, model.name)).all()
        out[model.__tablename__ + "_duplicate_names"] = sum(c - 1 for c in Counter(keys).values() if c > 1)
    out["pipe_duplicate_connections"] = db.execute(text(
        "SELECT COUNT(*) FROM (SELECT from_node_id, to_node_id FROM pipes GROUP BY 1,2 HAVING COUNT(*)>1)")).scalar_one()
    out["telemetry_duplicate_readings"] = db.execute(text(
        "SELECT COUNT(*) FROM (SELECT sensor_id, timestamp FROM telemetry GROUP BY 1,2 HAVING COUNT(*)>1)")).scalar_one()
    out["total"] = int(sum(v for v in out.values()))
    return out


def missing_value_checks(db: Session) -> dict:
    total = db.scalar(select(func.count(Telemetry.id))) or 0
    missing = db.scalar(select(func.count(Telemetry.id)).where(Telemetry.value.is_(None))) or 0
    by_sensor = db.execute(select(Telemetry.sensor_id, func.count(Telemetry.id))
                           .where(Telemetry.value.is_(None)).group_by(Telemetry.sensor_id)).all()
    master_nulls = {}
    for model in (Facility, Pump, Tank, Valve, Pipe, Sensor):
        cols = [c for c in model.__table__.columns if not c.nullable]
        n = 0
        for c in cols:
            n += db.scalar(select(func.count()).select_from(model).where(c.is_(None))) or 0
        master_nulls[model.__tablename__] = n
    return {"telemetry_rows": total, "telemetry_missing_values": missing,
            "telemetry_missing_pct": round(missing / total * 100, 4) if total else 0.0,
            "missing_by_sensor": [{"sensor_id": s, "missing": c} for s, c in by_sensor],
            "required_field_nulls": master_nulls}


def invalid_sensor_readings(db: Session, limit: int = 100) -> dict:
    rows = db.execute(text(
        "SELECT s.id, s.tag, s.facility_id, s.sensor_type, s.min_range, s.max_range, "
        "SUM(CASE WHEN t.value < s.min_range OR t.value > s.max_range THEN 1 ELSE 0 END) AS out_of_range, "
        "SUM(CASE WHEN t.value IS NULL THEN 1 ELSE 0 END) AS missing, "
        "MIN(t.value), MAX(t.value), COUNT(t.id) "
        "FROM sensors s JOIN telemetry t ON t.sensor_id = s.id GROUP BY s.id ORDER BY s.id")).all()
    items = [{"sensor_id": r[0], "tag": r[1], "facility_id": r[2], "sensor_type": r[3], "range": [r[4], r[5]],
              "out_of_range": int(r[6] or 0), "missing": int(r[7] or 0), "min_value": r[8], "max_value": r[9],
              "readings": r[10]} for r in rows if (r[6] or 0) > 0 or (r[7] or 0) > 0]
    return {"sensors_with_invalid_readings": len(items),
            "out_of_range_readings": sum(i["out_of_range"] for i in items),
            "missing_readings": sum(i["missing"] for i in items), "items": items[:limit]}


def tank_capacity_checks(db: Session) -> dict:
    violations = []
    for t in db.scalars(select(Tank)).all():
        if t.initial_level_pct > 100 or t.initial_level_pct < 0:
            violations.append({"tank_id": t.id, "type": "CONFIG", "message": f"Initial level {t.initial_level_pct}% "
                               "outside 0-100 %."})
    rows = db.execute(text(
        "SELECT s.equipment_id, COUNT(*), MAX(t.value), MIN(t.timestamp), MAX(t.timestamp), MAX(t.derived_value) "
        "FROM telemetry t JOIN sensors s ON s.id = t.sensor_id "
        "WHERE s.sensor_type = 'LEVEL' AND (t.value > 100 OR t.value < 0) GROUP BY s.equipment_id")).all()
    caps = dict(db.execute(select(Tank.id, Tank.capacity_m3)).all())
    for tid, n, mx, t0, t1, mxv in rows:
        violations.append({"tank_id": tid, "type": "READING", "count": n, "max_level_pct": mx,
                           "max_volume_m3": mxv, "capacity_m3": caps.get(tid), "first": str(t0), "last": str(t1),
                           "message": f"{n} level reading(s) outside 0-100 % (max {mx}%): stored volume would exceed "
                                      f"capacity {caps.get(tid)} m3 - physically impossible, flagged as instrument fault."})
    at_full = db.execute(text(
        "SELECT s.equipment_id, COUNT(*) FROM telemetry t JOIN sensors s ON s.id = t.sensor_id "
        "JOIN tanks k ON k.id = s.equipment_id WHERE s.sensor_type='LEVEL' AND t.value >= k.high_alarm_pct "
        "AND t.value <= 100 GROUP BY s.equipment_id")).all()
    high = [{"tank_id": tid, "samples_at_or_above_high_alarm": n} for tid, n in at_full]
    return {"violation_count": len(violations), "violations": violations, "high_level_tanks": high}


def mass_balance_checks(db: Session, tolerance_pct: float | None = None) -> dict:
    out = []
    totals = []
    for fac_id in db.scalars(select(Facility.id).order_by(Facility.id)).all():
        model = build_process_model(snapshot_from_db(db, fac_id))
        ts, readings = load_wide(db, fac_id)
        if not ts:
            continue
        step = infer_step_minutes(ts)
        win = max(int(24 * 60 / step), 4)
        kwargs = {} if tolerance_pct is None else {"tolerance_pct": tolerance_pct}
        whole = facility_balance(model, readings, step, 0, len(ts), **kwargs)
        totals.append({"facility_id": fac_id, "balance_error_pct": whole["balance_error_pct"],
                       "status": whole["status"], "classification": whole["classification"],
                       "residual_m3": whole["residual_m3"], "total_inflow_m3": whole["total_inflow_m3"]})
        for s in range(0, len(ts), win):
            e = min(s + win, len(ts))
            if e - s < win // 4:
                continue
            mb = facility_balance(model, readings, step, s, e, **kwargs)
            if mb["status"] in ("WARNING", "EXCEPTION"):
                out.append({"facility_id": fac_id, "start": ts[s].isoformat(), "end": ts[e - 1].isoformat(),
                            "balance_error_pct": mb["balance_error_pct"], "status": mb["status"],
                            "residual_m3": mb["residual_m3"], "classification": mb["classification"],
                            "message": f"Inflow {mb['total_inflow_m3']} m3 - outflow {mb['total_outflow_m3']} m3 - "
                                       f"storage change {mb['storage_change_m3']} m3 = residual {mb['residual_m3']} m3 "
                                       f"({mb['balance_error_pct']}% > tolerance {mb['tolerance_pct']}%)."})
    errs = [t["balance_error_pct"] for t in totals if t["balance_error_pct"] is not None]
    return {"failures": out, "failure_count": len(out), "facility_totals": totals,
            "mean_abs_balance_error_pct": round(float(np.mean(errs)), 3) if errs else None}


def simulation_checks(db: Session) -> dict:
    runs = db.scalars(select(SimulationRun).order_by(SimulationRun.id)).all()
    errors = []
    for r in runs:
        if r.status == "FAILED":
            errors.append({"simulation_id": r.id, "type": "INPUT_VALIDATION", "errors": r.validation_errors or []})
        if r.status == "COMPLETED":
            missing = [k for k in ("original_config", "modified_parameters", "effective_config") if not getattr(r, k)]
            if missing:
                errors.append({"simulation_id": r.id, "type": "MISSING_INPUT_CONFIGURATION",
                               "errors": [{"field": m, "message": f"Completed run has no {m}; outputs are not "
                                                                  "traceable to inputs."} for m in missing]})
    completed = sum(1 for r in runs if r.status == "COMPLETED")
    return {"total_runs": len(runs), "completed": completed, "failed": len(runs) - completed,
            "success_rate_pct": round(completed / len(runs) * 100, 2) if runs else None, "errors": errors}


def topology_checks(db: Session) -> dict:
    out = []
    for fac_id in db.scalars(select(Facility.id).order_by(Facility.id)).all():
        topo = facility_topology(db, fac_id)
        v = topo["validation"]
        out.append({"facility_id": fac_id, "is_valid": v["is_valid"], "errors": v["error_count"],
                    "warnings": v["warning_count"], "components": len(v["components"]),
                    "issues": v["issues"]})
    return {"facilities": out, "valid_facilities": sum(1 for f in out if f["is_valid"]), "total": len(out)}


def alarm_history_checks(db: Session) -> dict:
    missing = db.execute(text(
        "SELECT COUNT(*) FROM alarms a WHERE NOT EXISTS (SELECT 1 FROM alarm_events e WHERE e.alarm_id = a.id)"
    )).scalar_one()
    return {"alarms_without_history": missing, "events": db.scalar(select(func.count(AlarmEvent.id)))}


def full_report(db: Session, tolerance_pct: float | None = None) -> dict:
    return {
        "primary_keys": primary_key_checks(db),
        "foreign_keys": foreign_key_checks(db),
        "duplicates": duplicate_checks(db),
        "missing_values": missing_value_checks(db),
        "topology": topology_checks(db),
        "tank_capacity": tank_capacity_checks(db),
        "mass_balance": mass_balance_checks(db, tolerance_pct),
        "sensor_readings": invalid_sensor_readings(db),
        "simulations": simulation_checks(db),
        "alarm_history": alarm_history_checks(db),
    }
