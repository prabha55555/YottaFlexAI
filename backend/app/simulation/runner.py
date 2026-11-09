"""Simulation studio service: validate -> execute -> detect -> balance -> persist.

Every run gets a new immutable SIM-<year>-<seq> record holding the original
configuration, the modified parameters, the effective configuration, outputs,
assumptions and any validation errors. Runs are never overwritten.
"""
from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.anomaly_detection.detector import Detector
from app.config import DEFAULT_SEED
from app.models import Alarm, OperatingMode, SimulationRun
from app.services.anomaly_service import _json_safe, persist_anomalies
from app.services.ids import next_simulation_id
from app.services.mass_balance import true_balance
from app.simulation.engine import FaultEvent, OperatingSettings, run_process
from app.simulation.process_model import build_process_model, snapshot_from_db
from app.simulation.scenarios import FAULT_KEYS, SCENARIOS, merge_parameters, preset_parameters, validate_parameters
from app.simulation.sensors import generate_readings

SIM_START = datetime(2026, 10, 22, 0, 0, 0)

BASE_ASSUMPTIONS = [
    "Simplified steady-state hydraulics per time step (quasi-static); no transients, water hammer or "
    "looped-network pressure solution. This is not a full industrial hydraulic solver.",
    "Incompressible water (rho = 1000 kg/m3); volume balance is used as the mass balance.",
    "Pump curve H(Q) = hf * (s^2 * H0 - k * Q^2) with affinity-law speed scaling; degradation scales the curve by hf.",
    "Pipe friction by Darcy-Weisbach with constant friction factor; valves use R = R100 / opening^2; "
    "blockage adds a contraction loss proportional to 1/(1 - restriction)^2.",
    "Tank volume integrates V(t+1) = V(t) + (Qin - Qout - Qleak) * dt with flows in m3/h and dt in hours; "
    "volume above capacity is spilled as overflow.",
    "Head tanks are fed by an external supply under proportional level control; end tanks feed consumer "
    "demand with a diurnal profile.",
    "Sensor readings = true value + Gaussian noise (accuracy-based), clipped to instrument range.",
    "Fault parameters (leaks, restrictions, pump health, sensor faults) are hidden from the detector; "
    "operational parameters (speed, availability, valve openings, demand, mode, initial levels) are known setpoints.",
]


def _canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, default=str, separators=(",", ":"))


def _r(a: np.ndarray, nd: int = 3) -> list:
    return [None if np.isnan(x) else round(float(x), nd) for x in a]


def build_settings(model, params: dict, mode: OperatingMode | None) -> OperatingSettings:
    demand = float(params.get("demand_factor", 1.0))
    speed_factor = 1.0
    if mode is not None:
        demand *= mode.demand_factor
        speed_factor = mode.pump_speed_factor
    speeds = {pid: min(p["speed_pct"] * speed_factor, 110.0) for pid, p in model.pumps.items()} \
        if speed_factor != 1.0 else {}
    speeds.update({k: float(v) for k, v in (params.get("pump_speeds") or {}).items()})
    return OperatingSettings(
        demand_factor=demand,
        pump_speed_pct=speeds,
        pump_available={k: bool(v) for k, v in (params.get("pump_availability") or {}).items()},
        valve_opening_pct={k: float(v) for k, v in (params.get("valve_openings") or {}).items()},
        tank_initial_level_pct={k: float(v) for k, v in (params.get("tank_initial_levels") or {}).items()},
        outlet_demand_m3h={k: float(v) for k, v in (params.get("flow_demand") or {}).items()},
    )


def build_faults(params: dict, start: int, steps: int) -> list[FaultEvent]:
    f = []
    for pid, v in (params.get("pipe_leaks") or {}).items():
        f.append(FaultEvent("PIPE_LEAK", pid, start, steps, float(v)))
    for pid, v in (params.get("pipe_restrictions") or {}).items():
        f.append(FaultEvent("PIPE_BLOCKAGE", pid, start, steps, float(v)))
    for pid, v in (params.get("pump_health") or {}).items():
        f.append(FaultEvent("PUMP_DEGRADATION", pid, start, steps, float(v)))
    for sid, mode in (params.get("sensor_faults") or {}).items():
        mode = str(mode).upper()
        mag = 0.12 if mode == "BIAS" else (3 if mode == "SPIKE" else 0.0)
        f.append(FaultEvent("SENSOR_FAULT", sid, start, steps, mag, mode))
    return f


class SimulationValidationError(Exception):
    def __init__(self, run: SimulationRun):
        self.run = run
        super().__init__("Simulation input validation failed")


def summarise(model, result: dict, readings: dict, anomalies: list[dict], mb: dict, tb: dict, dt_h: float) -> dict:
    lines = {}
    energy = 0.0
    for pid, o in result["lines"].items():
        e = float(o["power_kw"].sum() * dt_h)
        energy += e
        run_mask = o["q_up"] > 0
        lines[pid] = {
            "mean_flow_m3h": round(float(o["q_up"].mean()), 2),
            "mean_delivered_m3h": round(float(o["q_down"].mean()), 2),
            "min_flow_m3h": round(float(o["q_up"].min()), 2),
            "max_discharge_pressure_bar": round(float(o["p_discharge"].max()), 3),
            "mean_efficiency": round(float(o["efficiency"][run_mask].mean()) if run_mask.any() else 0.0, 3),
            "energy_kwh": round(e, 1),
            "leak_volume_m3": round(float(o["leak"].sum() * dt_h), 2),
        }
    tanks = {}
    for tid, o in result["tanks"].items():
        tanks[tid] = {
            "start_level_pct": round(float(o["level_pct"][0]), 2),
            "end_level_pct": round(float(result["final_volume"][tid] / model.tanks[tid]["capacity_m3"] * 100), 2),
            "min_level_pct": round(float(o["level_pct"].min()), 2),
            "max_level_pct": round(float(o["level_pct"].max()), 2),
            "overflow_m3": round(float(o["overflow_m3"].sum()), 2),
        }
    by_type: dict[str, int] = {}
    by_sev: dict[str, int] = {}
    for a in anomalies:
        by_type[a["anomaly_type"]] = by_type.get(a["anomaly_type"], 0) + 1
        by_sev[a["severity"]] = by_sev.get(a["severity"], 0) + 1
    delivered = sum(float(o["q"].sum()) for o in result["outlets"].values()) * dt_h
    demanded = sum(float(o["demand"].sum()) for o in result["outlets"].values()) * dt_h
    return {
        "kpis": {
            "total_inflow_m3": tb["total_inflow_m3"],
            "total_outflow_m3": tb["total_outflow_m3"],
            "demand_m3": round(demanded, 2),
            "demand_served_pct": round(delivered / demanded * 100, 2) if demanded > 0 else None,
            "true_leak_m3": tb["true_leak_m3"],
            "overflow_m3": tb["overflow_m3"],
            "storage_change_m3": tb["storage_change_m3"],
            "pump_energy_kwh": round(energy, 1),
            "specific_energy_kwh_per_m3": round(energy / tb["total_outflow_m3"], 4) if tb["total_outflow_m3"] > 0 else None,
            "measured_balance_error_pct": mb.get("balance_error_pct"),
            "mass_balance_status": mb.get("status"),
            "anomaly_count": len(anomalies),
            "critical_anomalies": by_sev.get("CRITICAL", 0),
        },
        "anomalies_by_type": by_type,
        "anomalies_by_severity": by_sev,
        "lines": lines,
        "tanks": tanks,
    }


def execute(model, settings: OperatingSettings, faults: list[FaultEvent], seed: int, steps: int,
            step_minutes: int, start: datetime = SIM_START):
    proc_ss, sens_ss = np.random.SeedSequence(seed).spawn(2)
    result = run_process(model, steps, step_minutes, start, settings, faults, np.random.default_rng(proc_ss))
    readings = generate_readings(model, result, np.random.default_rng(sens_ss),
                                 [f for f in faults if f.kind == "SENSOR_FAULT"])
    det = Detector(model, settings).detect(readings, result["timestamps"], step_minutes)
    return result, readings, det


def run_simulation(db: Session, facility_id: str, scenario: str, parameters: dict | None = None, *,
                   seed: int = DEFAULT_SEED, steps: int = 96, step_minutes: int = 15,
                   fault_start_step: int | None = None, name: str = "", baseline_simulation_id: str | None = None,
                   run_baseline: bool = False, apply_preset: bool = True) -> SimulationRun:
    t0 = time.perf_counter()
    scenario = (scenario or "").upper()
    original = snapshot_from_db(db, facility_id)
    model = build_process_model(original)
    user_params = parameters or {}
    params = merge_parameters(preset_parameters(model, scenario) if apply_preset else {}, user_params)
    fault_start = steps // 4 if fault_start_step is None else fault_start_step
    mode_ids = set(db.scalars(select(OperatingMode.id)).all())
    errors = []
    if scenario not in SCENARIOS:
        errors.append({"field": "scenario", "message": f"Unknown scenario '{scenario}'. "
                                                       f"Allowed: {', '.join(SCENARIOS)}."})
    if not original["pumps"] and not original["tanks"]:
        errors.append({"field": "facility_id", "message": f"Facility {facility_id} has no equipment to simulate."})
    errors += validate_parameters(model, params, steps, step_minutes, fault_start, mode_ids)

    now = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)
    sim_id = next_simulation_id(db, now.year)
    input_doc = {"facility_id": facility_id, "scenario": scenario, "parameters": params, "seed": seed,
                 "steps": steps, "step_minutes": step_minutes, "fault_start_step": fault_start,
                 "original_config": original}
    input_hash = hashlib.sha256(_canonical(input_doc).encode()).hexdigest()
    run = SimulationRun(
        id=sim_id, facility_id=facility_id, name=name or f"{scenario.title()} - {facility_id}", scenario=scenario,
        seed=seed, steps=steps, step_minutes=step_minutes, start_time=SIM_START, original_config=original,
        modified_parameters={"user": user_params, "resolved": params, "fault_start_step": fault_start},
        input_hash=input_hash, created_at=now, baseline_simulation_id=baseline_simulation_id,
    )
    if errors:
        run.status = "FAILED"
        run.validation_errors = errors
        run.assumptions = BASE_ASSUMPTIONS
        run.duration_ms = round((time.perf_counter() - t0) * 1000, 1)
        db.add(run)
        db.commit()
        raise SimulationValidationError(run)

    mode = db.get(OperatingMode, params["operating_mode_id"]) if params.get("operating_mode_id") else None
    settings = build_settings(model, params, mode)
    faults = build_faults(params, fault_start, steps)
    result, readings, det = execute(model, settings, faults, seed, steps, step_minutes)
    dt_h = step_minutes / 60
    mb = det.mass_balance[0] if det.mass_balance else {}
    tb = true_balance(model, result)

    ts_iso = [t.isoformat() for t in result["timestamps"]]
    run.status = "COMPLETED"
    run.effective_config = {
        "operating_settings": {
            "demand_factor": settings.demand_factor, "pump_speed_pct": settings.pump_speed_pct,
            "pump_available": settings.pump_available, "valve_opening_pct": settings.valve_opening_pct,
            "tank_initial_level_pct": settings.tank_initial_level_pct, "outlet_demand_m3h": settings.outlet_demand_m3h,
            "operating_mode": mode.name if mode else None,
        },
        "injected_faults": [f.to_dict() for f in faults],
        "known_to_detector": ["operating_settings"],
        "hidden_from_detector": [k for k in FAULT_KEYS if params.get(k)],
    }
    run.summary = summarise(model, result, readings, det.anomalies, mb, tb, dt_h)
    run.mass_balance = {"measured": _json_safe(mb), "true_closure": tb}
    run.timeseries = {
        "timestamps": ts_iso,
        "lines": {pid: {k: _r(o[k]) for k in ("q_up", "q_down", "p_suction", "p_discharge", "head", "efficiency")}
                  for pid, o in result["lines"].items()},
        "tanks": {tid: {"level_pct": _r(o["level_pct"]), "volume_m3": _r(o["volume_m3"], 1)}
                  for tid, o in result["tanks"].items()},
        "inlets": {vid: {"q": _r(o["q"])} for vid, o in result["inlets"].items()},
        "outlets": {vid: {"q": _r(o["q"]), "demand": _r(o["demand"])} for vid, o in result["outlets"].items()},
    }
    run.readings = {sid: _r(v) for sid, v in readings.items()}
    assumptions = list(BASE_ASSUMPTIONS)
    if faults:
        assumptions.append(f"Faults are active from step {fault_start} "
                           f"({result['timestamps'][fault_start].isoformat()}) to the end of the run.")
    if model.issues:
        assumptions.append(f"{len(model.issues)} topology issue(s) excluded equipment from the hydraulic model: "
                           + "; ".join(i['issue'] for i in model.issues[:5]))
    run.assumptions = assumptions
    run.validation_errors = []
    db.add(run)
    db.flush()
    persist_anomalies(db, det.anomalies, "SIMULATION", simulation_id=sim_id)
    run.duration_ms = round((time.perf_counter() - t0) * 1000, 1)
    db.commit()

    if run_baseline and baseline_simulation_id is None and (scenario != "NORMAL" or user_params):
        base = run_simulation(db, facility_id, "NORMAL", {}, seed=seed, steps=steps, step_minutes=step_minutes,
                              fault_start_step=fault_start, name=f"Baseline for {sim_id}", apply_preset=False)
        run.baseline_simulation_id = base.id
        db.commit()
    return run


def compare_runs(base: SimulationRun, mod: SimulationRun) -> dict:
    kb = (base.summary or {}).get("kpis", {})
    km = (mod.summary or {}).get("kpis", {})
    deltas = {}
    for k in sorted(set(kb) | set(km)):
        a, b = kb.get(k), km.get(k)
        if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool):
            deltas[k] = {"baseline": a, "modified": b, "delta": round(b - a, 4),
                         "delta_pct": round((b - a) / abs(a) * 100, 2) if a not in (0, None) else None}
        else:
            deltas[k] = {"baseline": a, "modified": b, "delta": None, "delta_pct": None}
    lines = {}
    for pid in sorted(set((base.summary or {}).get("lines", {})) | set((mod.summary or {}).get("lines", {}))):
        lb = base.summary["lines"].get(pid, {})
        lm = mod.summary["lines"].get(pid, {})
        lines[pid] = {k: {"baseline": lb.get(k), "modified": lm.get(k)} for k in set(lb) | set(lm)}
    tanks = {}
    for tid in sorted(set((base.summary or {}).get("tanks", {})) | set((mod.summary or {}).get("tanks", {}))):
        tb_ = base.summary["tanks"].get(tid, {})
        tm = mod.summary["tanks"].get(tid, {})
        tanks[tid] = {k: {"baseline": tb_.get(k), "modified": tm.get(k)} for k in set(tb_) | set(tm)}
    warnings = []
    if base.facility_id != mod.facility_id:
        warnings.append("Runs belong to different facilities.")
    if (base.steps, base.step_minutes) != (mod.steps, mod.step_minutes):
        warnings.append("Runs have different horizons; time-series overlay is truncated to the shorter run.")
    if base.seed != mod.seed:
        warnings.append("Runs use different seeds; demand noise and sensor noise differ.")
    return {
        "baseline_id": base.id, "modified_id": mod.id, "baseline_scenario": base.scenario,
        "modified_scenario": mod.scenario, "kpis": deltas, "lines": lines, "tanks": tanks, "warnings": warnings,
        "anomalies_by_type": {"baseline": (base.summary or {}).get("anomalies_by_type", {}),
                              "modified": (mod.summary or {}).get("anomalies_by_type", {})},
    }


def alarms_for_run(db: Session, sim_id: str) -> list[Alarm]:
    return db.scalars(select(Alarm).where(Alarm.simulation_id == sim_id).order_by(Alarm.id)).all()
