"""Dashboard, analytics, evaluation and data-validation endpoints.

Every number returned here is computed from database contents.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import timedelta

import numpy as np
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import RHO_G_BAR_PER_M
from app.database import get_db
from app.models import Alarm, Anomaly, Facility, Pipe, Pump, Sensor, SimulationRun, Tank, Telemetry, Valve
from app.services.evaluation_service import active_dataset, evaluate, load_ground_truth
from app.services.telemetry_service import load_wide
from app.simulation.process_model import build_process_model, snapshot_from_db, tank_level_sensor
from app.validation import integrity
from app.validation.negative_scenarios import run_all as run_negative_cases
from app.api.telemetry import facility_hourly

router = APIRouter()
SEV_RANK = {"LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}


def _open_alarms(db: Session, facility_id: str | None):
    stmt = select(Alarm).where(Alarm.simulation_id.is_(None), Alarm.status.in_(("ACTIVE", "ACKNOWLEDGED")))
    if facility_id:
        stmt = stmt.where(Alarm.facility_id == facility_id)
    return db.scalars(stmt).all()


def _equipment_health(db: Session, facility_id: str | None) -> dict:
    alarms = _open_alarms(db, facility_id)
    sensor_eq = dict(db.execute(select(Sensor.id, Sensor.equipment_id)).all())
    anomaly_sensor = dict(db.execute(select(Anomaly.id, Anomaly.sensor_id).where(
        Anomaly.id.in_([a.anomaly_id for a in alarms if a.anomaly_id]))).all())
    worst: dict[str, int] = {}
    for a in alarms:
        for eid in (a.equipment_id, sensor_eq.get(a.equipment_id), anomaly_sensor.get(a.anomaly_id)):
            if eid:
                worst[eid] = max(worst.get(eid, 0), SEV_RANK[a.severity])
    out = {}
    for name, model in (("pumps", Pump), ("tanks", Tank), ("valves", Valve), ("pipes", Pipe), ("sensors", Sensor)):
        stmt = select(model.id)
        if facility_id:
            stmt = stmt.where(model.facility_id == facility_id)
        ids = db.scalars(stmt).all()
        c = {"NORMAL": 0, "WARNING": 0, "CRITICAL": 0}
        for i in ids:
            r = worst.get(i, 0)
            c["CRITICAL" if r >= 3 else "WARNING" if r >= 1 else "NORMAL"] += 1
        out[name] = c
    return out


@router.get("/dashboard/summary", tags=["dashboard"])
def dashboard(facility_id: str | None = None, db: Session = Depends(get_db)):
    facs = db.scalars(select(Facility).order_by(Facility.id)).all()
    if facility_id and not any(f.id == facility_id for f in facs):
        raise HTTPException(404, f"Facility {facility_id} not found")

    def count(model):
        stmt = select(func.count(model.id))
        if facility_id:
            stmt = stmt.where(model.facility_id == facility_id)
        return db.scalar(stmt)

    counts = {n: count(m) for n, m in (("pumps", Pump), ("tanks", Tank), ("valves", Valve), ("pipes", Pipe),
                                       ("sensors", Sensor))}
    alarms = _open_alarms(db, facility_id)
    crit_q = select(func.count(Anomaly.id)).where(Anomaly.severity == "CRITICAL", Anomaly.source == "TELEMETRY_SCAN")
    if facility_id:
        crit_q = crit_q.where(Anomaly.facility_id == facility_id)
    tel_q = select(func.count(Telemetry.id))
    if facility_id:
        tel_q = tel_q.join(Sensor, Sensor.id == Telemetry.sensor_id).where(Sensor.facility_id == facility_id)
    plant = []
    for f in facs:
        fa = [a for a in _open_alarms(db, f.id)]
        top = max((SEV_RANK[a.severity] for a in fa), default=0)
        plant.append({"facility_id": f.id, "name": f.name, "status": f.status,
                      "operating_mode": f.operating_mode.name if f.operating_mode else None,
                      "open_alarms": len(fa), "critical_alarms": sum(1 for a in fa if a.severity == "CRITICAL"),
                      "condition": "ALARM" if top >= 3 else "WARNING" if top >= 1 else "NORMAL"})
    target = facility_id or (facs[0].id if facs else None)
    trends = facility_hourly(db, target) if target else None
    tank_levels = []
    tank_q = select(Tank)
    if facility_id:
        tank_q = tank_q.where(Tank.facility_id == facility_id)
    tanks = db.scalars(tank_q.order_by(Tank.id)).all()
    lvl_sensors = {s.equipment_id: s for s in db.scalars(select(Sensor).where(Sensor.sensor_type == "LEVEL")).all()}
    last_ts = db.scalar(select(func.max(Telemetry.timestamp)))
    if last_ts:
        vals = dict(db.execute(select(Telemetry.sensor_id, Telemetry.value).where(Telemetry.timestamp == last_ts)).all())
        for t in tanks:
            s = lvl_sensors.get(t.id)
            v = vals.get(s.id) if s else None
            tank_levels.append({"tank_id": t.id, "name": t.name, "facility_id": t.facility_id,
                                "level_pct": v, "capacity_m3": t.capacity_m3,
                                "volume_m3": round(v / 100 * t.capacity_m3, 1) if v is not None else None,
                                "high_alarm_pct": t.high_alarm_pct, "low_alarm_pct": t.low_alarm_pct})
    sim_q = select(SimulationRun).order_by(SimulationRun.created_at.desc(), SimulationRun.id.desc()).limit(6)
    if facility_id:
        sim_q = sim_q.where(SimulationRun.facility_id == facility_id)
    sims = [{"id": s.id, "facility_id": s.facility_id, "scenario": s.scenario, "status": s.status,
             "created_at": s.created_at, "anomalies": (s.summary or {}).get("kpis", {}).get("anomaly_count"),
             "balance_status": (s.summary or {}).get("kpis", {}).get("mass_balance_status")}
            for s in db.scalars(sim_q).all()]
    return {
        "facility_id": facility_id,
        "totals": {"facilities": len(facs) if not facility_id else 1, "equipment": sum(counts.values()),
                   **counts, "active_alarms": len(alarms),
                   "critical_alarms": sum(1 for a in alarms if a.severity == "CRITICAL"),
                   "critical_anomalies": db.scalar(crit_q), "telemetry_records": db.scalar(tel_q)},
        "equipment_health": _equipment_health(db, facility_id),
        "plant_status": plant,
        "trend_facility_id": target,
        "trends": trends,
        "tank_levels": tank_levels,
        "latest_timestamp": last_ts,
        "recent_simulations": sims,
        "simulated_data": True,
    }


@router.get("/analytics/overview", tags=["analytics"])
def analytics(facility_id: str, db: Session = Depends(get_db)):
    if not db.get(Facility, facility_id):
        raise HTTPException(404, f"Facility {facility_id} not found")
    model = build_process_model(snapshot_from_db(db, facility_id))
    ts, data = load_wide(db, facility_id)

    def clean(sid):
        if sid is None or sid not in data:
            return None
        s = model.sensors[sid]
        v = data[sid]
        return np.where((v < s["min_range"]) | (v > s["max_range"]), np.nan, v)

    def stat(v, fn):
        return None if v is None or np.isnan(v).all() else round(float(fn(v)), 3)

    pumps = []
    flows = []
    pressures = []
    for ln in model.lines:
        p = model.pumps[ln.pump_id]
        qu, qd = clean(ln.sensors.get("flow_up")), clean(ln.sensors.get("flow_down"))
        ps, pd_ = clean(ln.sensors.get("p_suction")), clean(ln.sensors.get("p_discharge"))
        s = p["speed_pct"] / 100
        perf = None
        if qu is not None and ps is not None and pd_ is not None:
            with np.errstate(all="ignore"):
                hc = p["health_factor"] * (s * s * p["shutoff_head_m"] - p["curve_k"] * qu**2)
                ratio = np.where((qu > 0.2 * p["rated_flow_m3h"]) & (hc > 1), (pd_ - ps) / RHO_G_BAR_PER_M / hc, np.nan)
            perf = stat(ratio, np.nanmedian)
            perf_min = stat(ratio, lambda x: np.nanpercentile(x, 5))
        else:
            perf_min = None
        pumps.append({"pump_id": ln.pump_id, "name": p["name"], "rated_flow_m3h": p["rated_flow_m3h"],
                      "mean_flow_m3h": stat(qu, np.nanmean),
                      "utilisation_pct": round(stat(qu, np.nanmean) / p["rated_flow_m3h"] * 100, 1)
                      if stat(qu, np.nanmean) is not None else None,
                      "performance_index": perf, "performance_index_p5": perf_min,
                      "health": "CRITICAL" if (perf_min or 1) < 0.8 else "WARNING" if (perf_min or 1) < 0.9 else "GOOD"})
        loss = None
        if qu is not None and qd is not None:
            su, sd = np.nansum(qu), np.nansum(qd)
            loss = round((su - sd) / su * 100, 2) if su > 0 else None
        flows.append({"pump_id": ln.pump_id, "pipe_id": ln.last_pipe_id, "mean_upstream_m3h": stat(qu, np.nanmean),
                      "mean_downstream_m3h": stat(qd, np.nanmean), "max_upstream_m3h": stat(qu, np.nanmax),
                      "line_loss_pct": loss,
                      "pipe_capacity_m3h": min(model.pipes[x]["max_flow_m3h"] for x in ln.pipe_ids)})
        rating = min(model.pipes[x]["max_pressure_bar"] for x in ln.discharge_pipe_ids) if ln.discharge_pipe_ids else None
        pressures.append({"pump_id": ln.pump_id, "mean_discharge_bar": stat(pd_, np.nanmean),
                          "max_discharge_bar": stat(pd_, np.nanmax), "min_discharge_bar": stat(pd_, np.nanmin),
                          "mean_suction_bar": stat(ps, np.nanmean), "pipe_rating_bar": rating,
                          "max_pct_of_rating": round(stat(pd_, np.nanmax) / rating * 100, 1)
                          if rating and stat(pd_, np.nanmax) is not None else None})
    tanks = []
    for tid, t in model.tanks.items():
        lv = clean(tank_level_sensor(model, tid))
        tanks.append({"tank_id": tid, "name": t["name"], "capacity_m3": t["capacity_m3"],
                      "mean_level_pct": stat(lv, np.nanmean), "min_level_pct": stat(lv, np.nanmin),
                      "max_level_pct": stat(lv, np.nanmax),
                      "time_above_high_pct": round(float(np.nanmean(lv >= t["high_alarm_pct"]) * 100), 2)
                      if lv is not None else None,
                      "time_below_low_pct": round(float(np.nanmean(lv <= t["low_alarm_pct"]) * 100), 2)
                      if lv is not None else None})

    an_rows = db.execute(select(Anomaly.anomaly_type, Anomaly.severity, Anomaly.source, func.count(Anomaly.id))
                         .where(Anomaly.facility_id == facility_id)
                         .group_by(Anomaly.anomaly_type, Anomaly.severity, Anomaly.source)).all()
    dist: dict = defaultdict(lambda: {"LOW": 0, "MEDIUM": 0, "HIGH": 0, "CRITICAL": 0, "total": 0,
                                      "TELEMETRY_SCAN": 0, "SIMULATION": 0})
    for typ, sev, src, n in an_rows:
        dist[typ][sev] += n
        dist[typ]["total"] += n
        dist[typ][src] += n

    alarm_rows = db.execute(select(Alarm.raised_at, Alarm.severity)
                            .where(Alarm.facility_id == facility_id, Alarm.simulation_id.is_(None))).all()
    buckets: dict = defaultdict(lambda: {"LOW": 0, "MEDIUM": 0, "HIGH": 0, "CRITICAL": 0})
    for raised, sev in alarm_rows:
        b = raised.replace(minute=0, second=0, microsecond=0)
        b = b - timedelta(hours=b.hour % 12)
        buckets[b][sev] += 1
    trend = [{"bucket": k.isoformat(), **v} for k, v in sorted(buckets.items())]

    sims = db.scalars(select(SimulationRun).where(SimulationRun.facility_id == facility_id)).all()
    per_scen: dict = defaultdict(lambda: {"runs": 0, "completed": 0, "failed": 0, "durations": [], "anomalies": [],
                                          "energy": [], "served": []})
    for s in sims:
        d = per_scen[s.scenario]
        d["runs"] += 1
        d["completed" if s.status == "COMPLETED" else "failed"] += 1
        if s.duration_ms:
            d["durations"].append(s.duration_ms)
        k = (s.summary or {}).get("kpis", {})
        if s.status == "COMPLETED":
            d["anomalies"].append(k.get("anomaly_count", 0))
            if k.get("pump_energy_kwh") is not None:
                d["energy"].append(k["pump_energy_kwh"])
            if k.get("demand_served_pct") is not None:
                d["served"].append(k["demand_served_pct"])

    def avg(x):
        return round(float(np.mean(x)), 2) if x else None

    sim_perf = [{"scenario": k, "runs": v["runs"], "completed": v["completed"], "failed": v["failed"],
                 "success_rate_pct": round(v["completed"] / v["runs"] * 100, 1),
                 "mean_duration_ms": avg(v["durations"]), "mean_anomalies": avg(v["anomalies"]),
                 "mean_energy_kwh": avg(v["energy"]), "mean_demand_served_pct": avg(v["served"])}
                for k, v in sorted(per_scen.items())]
    return {"facility_id": facility_id, "period": {"start": ts[0].isoformat() if ts else None,
                                                   "end": ts[-1].isoformat() if ts else None},
            "equipment_health": pumps, "flow_analysis": flows, "pressure_analysis": pressures,
            "tank_utilisation": tanks, "anomaly_distribution": [{"anomaly_type": k, **v} for k, v in sorted(dist.items())],
            "alarm_trend": trend, "simulation_performance": sim_perf}


# --------------------------------------------------------------- evaluation
@router.get("/evaluation/metrics", tags=["evaluation"])
def evaluation_metrics(db: Session = Depends(get_db)):
    return evaluate(db)


@router.get("/evaluation/ground-truth", tags=["evaluation"])
def ground_truth():
    gt = load_ground_truth()
    if gt is None:
        raise HTTPException(404, "Ground truth not found. Run python -m scripts.generate_data first.")
    return gt


@router.get("/evaluation/data-quality", tags=["evaluation"])
def data_quality(db: Session = Depends(get_db)):
    pk = integrity.primary_key_checks(db)
    fk = integrity.foreign_key_checks(db)
    dup = integrity.duplicate_checks(db)
    miss = integrity.missing_value_checks(db)
    topo = integrity.topology_checks(db)
    sims = integrity.simulation_checks(db)
    mb = integrity.mass_balance_checks(db)
    return {
        "dataset": active_dataset(),
        "primary_key_integrity_pct": round((1 - pk["error_count"] / max(pk["checked_records"], 1)) * 100, 4),
        "primary_key_errors": pk["error_count"],
        "foreign_key_integrity_pct": round((1 - fk["error_count"] / max(fk["checked_relationships"], 1)) * 100, 4),
        "foreign_key_errors": fk["error_count"],
        "duplicate_count": dup["total"], "duplicates": dup,
        "missing_value_pct": miss["telemetry_missing_pct"], "missing_values": miss["telemetry_missing_values"],
        "topology_valid_facilities": topo["valid_facilities"], "topology_total_facilities": topo["total"],
        "simulation_success_rate_pct": sims["success_rate_pct"], "simulation_runs": sims["total_runs"],
        "mass_balance_mean_abs_error_pct": mb["mean_abs_balance_error_pct"],
        "mass_balance_facility_totals": mb["facility_totals"],
    }


# --------------------------------------------------------------- validation
@router.get("/validation/report", tags=["validation"])
def validation_report(tolerance_pct: float | None = None, db: Session = Depends(get_db)):
    return integrity.full_report(db, tolerance_pct)


@router.get("/validation/negative-scenarios", tags=["validation"])
def negative_scenarios():
    return run_negative_cases()
