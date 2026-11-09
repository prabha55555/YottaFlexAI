"""Scenario presets and parameter validation for the simulation studio."""
from __future__ import annotations

from app.simulation.process_model import ProcessModel, tank_level_sensor
from app.simulation.sensors import SENSOR_FAULT_MODES

SCENARIOS = {
    "NORMAL": "Normal operation with the stored configuration.",
    "LEAKAGE": "A leak on a transfer main loses part of the pumped flow before the delivery meter.",
    "BLOCKAGE": "Partial blockage (flow-area restriction) on a transfer main.",
    "PUMP_DEGRADATION": "Worn pump: head reduced across its curve (health factor < 1).",
    "SENSOR_MALFUNCTION": "Instrument faults (bias on a delivery flow meter, flatline on a pressure transmitter).",
    "HIGH_DEMAND": "Consumer demand increased by 50 %.",
    "VALVE_CLOSURE": "A discharge control valve is closed while its pump keeps running.",
    "TANK_OVERCAPACITY": "End tank starts high and its outlet valve is throttled -> overfill.",
}

PARAMETER_KEYS = ("operating_mode_id", "demand_factor", "pump_speeds", "pump_availability", "valve_openings",
                  "tank_initial_levels", "flow_demand", "pipe_restrictions", "pipe_leaks", "pump_health",
                  "sensor_faults")
FAULT_KEYS = ("pipe_restrictions", "pipe_leaks", "pump_health", "sensor_faults")
ALLOWED_STEP_MINUTES = (5, 10, 15, 30, 60)
MIN_STEPS, MAX_STEPS = 8, 672


def preset_parameters(model: ProcessModel, scenario: str) -> dict:
    """Deterministic default targets for a scenario (first eligible equipment)."""
    lines = sorted(model.lines, key=lambda ln: ln.pump_id)
    p: dict = {}
    if not lines:
        return p
    first = lines[0]
    if scenario == "LEAKAGE":
        p["pipe_leaks"] = {first.last_pipe_id: 0.15}
    elif scenario == "BLOCKAGE":
        p["pipe_restrictions"] = {first.last_pipe_id: 60.0}
    elif scenario == "PUMP_DEGRADATION":
        p["pump_health"] = {first.pump_id: 0.75}
    elif scenario == "SENSOR_MALFUNCTION":
        sf = {}
        if "flow_down" in first.sensors:
            sf[first.sensors["flow_down"]] = "BIAS"
        second = lines[1] if len(lines) > 1 else first
        if "p_discharge" in second.sensors:
            sf[second.sensors["p_discharge"]] = "FLATLINE"
        p["sensor_faults"] = sf
    elif scenario == "HIGH_DEMAND":
        p["demand_factor"] = 1.5
    elif scenario == "VALVE_CLOSURE":
        dv = [i for k, i in first.discharge_path if k == "VALVE"]
        if dv:
            p["valve_openings"] = {dv[0]: 0.0}
    elif scenario == "TANK_OVERCAPACITY" and model.outlets:
        ob = sorted(model.outlets, key=lambda b: b.valve_id)[0]
        p["tank_initial_levels"] = {ob.tank_id: 85.0}
        p["valve_openings"] = {ob.valve_id: 10.0}
    return p


def merge_parameters(preset: dict, user: dict) -> dict:
    """User parameters override preset ones; dict-valued keys are merged."""
    out = {k: (dict(v) if isinstance(v, dict) else v) for k, v in preset.items()}
    for k, v in (user or {}).items():
        if v is None:
            continue
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k].update(v)
        else:
            out[k] = v
    return out


def validate_parameters(model: ProcessModel, params: dict, steps: int, step_minutes: int,
                        fault_start_step: int, mode_ids: set[str]) -> list[dict]:
    errors: list[dict] = []

    def err(field: str, msg: str):
        errors.append({"field": field, "message": msg})

    if not (MIN_STEPS <= steps <= MAX_STEPS):
        err("steps", f"steps must be between {MIN_STEPS} and {MAX_STEPS} (got {steps}).")
    if step_minutes not in ALLOWED_STEP_MINUTES:
        err("step_minutes", f"step_minutes must be one of {ALLOWED_STEP_MINUTES} (got {step_minutes}).")
    if not (0 <= fault_start_step < max(steps, 1)):
        err("fault_start_step", f"fault_start_step must be within [0, steps) (got {fault_start_step}).")
    for k in params:
        if k not in PARAMETER_KEYS:
            err(k, f"Unknown parameter '{k}'. Allowed: {', '.join(PARAMETER_KEYS)}.")

    def check_map(key, pool, lo, hi, label, allow_bool=False):
        for eid, val in (params.get(key) or {}).items():
            if eid not in pool:
                err(f"{key}.{eid}", f"{eid} is not a {label} of facility {model.facility_id}.")
                continue
            if allow_bool:
                if not isinstance(val, bool):
                    err(f"{key}.{eid}", "Value must be true or false.")
                continue
            if not isinstance(val, (int, float)) or isinstance(val, bool) or not (lo <= val <= hi):
                err(f"{key}.{eid}", f"Value {val!r} outside allowed range [{lo}, {hi}].")

    check_map("pump_speeds", model.pumps, 0, 110, "pump")
    check_map("pump_availability", model.pumps, 0, 0, "pump", allow_bool=True)
    check_map("valve_openings", model.valves, 0, 100, "valve")
    check_map("tank_initial_levels", model.tanks, 0, 100, "tank")
    check_map("pipe_restrictions", model.pipes, 0, 95, "pipe")
    check_map("pipe_leaks", model.pipes, 0.0, 0.5, "pipe")
    check_map("pump_health", model.pumps, 0.3, 1.0, "pump")
    outlet_valves = {b.valve_id: model.valves[b.valve_id] for b in model.outlets}
    for vid, val in (params.get("flow_demand") or {}).items():
        if vid not in outlet_valves:
            err(f"flow_demand.{vid}", f"{vid} is not an OUTLET valve of facility {model.facility_id}.")
        elif not isinstance(val, (int, float)) or val < 0 or val > 3 * (outlet_valves[vid]["boundary_flow_m3h"] or 0):
            err(f"flow_demand.{vid}", f"Demand {val!r} m3/h outside [0, 3x nominal].")
    leak_ok = {p for ln in model.lines for p in ln.discharge_pipe_ids}
    for pid in (params.get("pipe_leaks") or {}):
        if pid in model.pipes and pid not in leak_ok:
            err(f"pipe_leaks.{pid}", f"Leaks can only be simulated on pump discharge pipes ({pid} is not one).")
    restr_ok = {p for ln in model.lines for p in ln.pipe_ids}
    for pid in (params.get("pipe_restrictions") or {}):
        if pid in model.pipes and pid not in restr_ok:
            err(f"pipe_restrictions.{pid}", f"{pid} is not part of a pump line; restriction has no hydraulic effect.")
    for sid, mode in (params.get("sensor_faults") or {}).items():
        if sid not in model.sensors:
            err(f"sensor_faults.{sid}", f"{sid} is not a sensor of facility {model.facility_id}.")
        elif str(mode).upper() not in SENSOR_FAULT_MODES:
            err(f"sensor_faults.{sid}", f"Unknown fault mode {mode!r}. Allowed: {', '.join(SENSOR_FAULT_MODES)}.")
        elif sid not in model.sensor_map:
            err(f"sensor_faults.{sid}", f"{sid} is not mapped to a simulated quantity.")
    df = params.get("demand_factor")
    if df is not None and (not isinstance(df, (int, float)) or not (0 <= df <= 3)):
        err("demand_factor", f"demand_factor must be within [0, 3] (got {df!r}).")
    mid = params.get("operating_mode_id")
    if mid is not None and mid not in mode_ids:
        err("operating_mode_id", f"Operating mode '{mid}' does not exist.")
    _ = tank_level_sensor
    return errors
