"""Time-stepping process engine (explicit Euler, fixed step).

Shared by the synthetic data generator and the simulation studio. Produces the
*true* process state; sensor readings (with noise and sensor faults) are derived
afterwards by ``app.simulation.sensors``.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import numpy as np

from app.simulation import hydraulics as hy
from app.simulation.process_model import ProcessModel

INLET_LEVEL_GAIN_PER_H = 0.5  # proportional level controller on inlet supply (1/h)
MIN_TANK_VOLUME_FRACTION = 0.02  # pumps cannot draw the tank below 2 %
SUPPLY_HEADER_BAR = 3.0  # nominal supply header pressure at INLET valves
DEMAND_NOISE_SIGMA = 0.02
DEMAND_NOISE_PHI = 0.9


@dataclass
class FaultEvent:
    """A time-windowed modification. ``end_step`` is exclusive.

    kinds: PIPE_LEAK (magnitude = leak fraction), PIPE_BLOCKAGE (magnitude = restriction %),
    PUMP_DEGRADATION (magnitude = health factor), SENSOR_FAULT (mode + magnitude),
    VALVE_POSITION (magnitude = opening %), PUMP_TRIP (pump unavailable),
    DEMAND_FACTOR (magnitude = multiplier).
    """

    kind: str
    target_id: str
    start_step: int
    end_step: int
    magnitude: float = 0.0
    mode: str | None = None
    event_id: str | None = None

    def active(self, step: int) -> bool:
        return self.start_step <= step < self.end_step

    def to_dict(self) -> dict:
        return {
            "kind": self.kind, "target_id": self.target_id, "start_step": self.start_step,
            "end_step": self.end_step, "magnitude": self.magnitude, "mode": self.mode, "event_id": self.event_id,
        }


@dataclass
class OperatingSettings:
    """Operator-controlled setpoints (known to the detector)."""

    demand_factor: float = 1.0
    pump_speed_pct: dict[str, float] = field(default_factory=dict)
    pump_available: dict[str, bool] = field(default_factory=dict)
    valve_opening_pct: dict[str, float] = field(default_factory=dict)
    tank_initial_level_pct: dict[str, float] = field(default_factory=dict)
    outlet_demand_m3h: dict[str, float] = field(default_factory=dict)


def demand_pattern(timestamps: list[datetime], rng: np.random.Generator | None) -> np.ndarray:
    """Diurnal consumer demand multiplier (mean ~1.0) with optional AR(1) noise."""
    hours = np.array([t.hour + t.minute / 60.0 for t in timestamps])
    base = 1.0 + 0.18 * np.sin(2 * np.pi * (hours - 9.0) / 24.0) + 0.05 * np.sin(2 * np.pi * (hours - 3.0) / 12.0)
    if rng is None:
        return base
    noise = np.zeros(len(timestamps))
    eps = rng.normal(0.0, DEMAND_NOISE_SIGMA, len(timestamps))
    for i in range(1, len(timestamps)):
        noise[i] = DEMAND_NOISE_PHI * noise[i - 1] + eps[i] * math.sqrt(1 - DEMAND_NOISE_PHI**2)
    return base + noise


def run_process(
    model: ProcessModel,
    n_steps: int,
    step_minutes: int,
    start_time: datetime,
    settings: OperatingSettings | None = None,
    faults: list[FaultEvent] | None = None,
    rng: np.random.Generator | None = None,
) -> dict:
    """Simulate ``n_steps`` and return true states.

    Result: {"timestamps": [...], "lines": {pump_id: {q_up,...}}, "tanks": {...},
             "inlets": {...}, "outlets": {...}}  with numpy arrays of length n_steps.
    Values at index t describe the state at the start of step t and the flows
    during [t, t+1).
    """
    settings = settings or OperatingSettings()
    faults = [f for f in (faults or []) if f.kind != "SENSOR_FAULT"]
    dt_h = step_minutes / 60.0
    timestamps = [start_time + timedelta(minutes=step_minutes * i) for i in range(n_steps)]
    pattern = demand_pattern(timestamps, rng)

    tanks = model.tanks
    vol = {}
    for tid, t in tanks.items():
        lvl = settings.tank_initial_level_pct.get(tid, t["initial_level_pct"])
        vol[tid] = t["capacity_m3"] * lvl / 100.0

    def arr() -> np.ndarray:
        return np.zeros(n_steps)

    line_keys = ("q_up", "q_down", "leak", "p_suction", "p_discharge", "p_down", "head", "running",
                 "speed_pct", "efficiency", "power_kw", "health")
    out_lines = {ln.pump_id: {k: arr() for k in line_keys} for ln in model.lines}
    out_tanks = {tid: {k: arr() for k in ("volume_m3", "level_pct", "inflow", "outflow", "leak_loss", "overflow_m3")}
                 for tid in tanks}
    out_inlets = {b.valve_id: {k: arr() for k in ("q", "p")} for b in model.inlets}
    out_outlets = {b.valve_id: {k: arr() for k in ("q", "demand")} for b in model.outlets}

    lines_from: dict[str, list] = {tid: [] for tid in tanks}
    lines_into: dict[str, list] = {tid: [] for tid in tanks}
    for ln in model.lines:
        lines_from[ln.src_tank_id].append(ln)
        lines_into[ln.dst_tank_id].append(ln)
    outlets_from = {tid: [b for b in model.outlets if b.tank_id == tid] for tid in tanks}
    inlets_into = {tid: [b for b in model.inlets if b.tank_id == tid] for tid in tanks}

    for step in range(n_steps):
        active = [f for f in faults if f.active(step)]
        leaks = {f.target_id: f.magnitude for f in active if f.kind == "PIPE_LEAK"}
        restrictions = {f.target_id: f.magnitude for f in active if f.kind == "PIPE_BLOCKAGE"}
        health = {f.target_id: f.magnitude for f in active if f.kind == "PUMP_DEGRADATION"}
        tripped = {f.target_id for f in active if f.kind == "PUMP_TRIP"}
        valve_open = dict(settings.valve_opening_pct)
        valve_open.update({f.target_id: f.magnitude for f in active if f.kind == "VALVE_POSITION"})
        demand_factor = settings.demand_factor
        for f in active:
            if f.kind == "DEMAND_FACTOR":
                demand_factor *= f.magnitude

        level = {tid: vol[tid] / tanks[tid]["capacity_m3"] * 100.0 for tid in tanks}
        liquid_h = {tid: level[tid] / 100.0 * tanks[tid]["height_m"] for tid in tanks}
        head_abs = {tid: tanks[tid]["elevation_m"] + liquid_h[tid] for tid in tanks}

        # --- 1. requested pump-line flows ------------------------------------
        line_state = {}
        for ln in model.lines:
            pump = model.pumps[ln.pump_id]
            speed = settings.pump_speed_pct.get(ln.pump_id, pump["speed_pct"])
            available = settings.pump_available.get(ln.pump_id, pump["available"]) and ln.pump_id not in tripped
            hf = health.get(ln.pump_id, pump["health_factor"])
            leak_pipe = next((p for p in ln.discharge_pipe_ids if p in leaks), None)
            f_leak = leaks.get(leak_pipe, 0.0) if leak_pipe else 0.0
            r_suc, r_up, r_down = model.line_resistances(ln, restrictions, valve_open, leak_pipe)
            s = speed / 100.0
            running = bool(available and s > 0)
            hs = head_abs[ln.dst_tank_id] - head_abs[ln.src_tank_id]
            q = hy.solve_operating_point(pump["shutoff_head_m"], pump["curve_k"], s if running else 0.0, hf,
                                         hs, r_suc + r_up, r_down, f_leak) if running else 0.0
            line_state[ln.pump_id] = {"q": q, "f_leak": f_leak, "running": running, "s": s, "hf": hf,
                                      "r_suc": r_suc, "pump": pump, "leak_pipe": leak_pipe}

        # --- 2. outlet demand -------------------------------------------------
        outlet_q = {}
        for b in model.outlets:
            v = model.valves[b.valve_id]
            nominal = settings.outlet_demand_m3h.get(b.valve_id, v.get("boundary_flow_m3h") or 0.0)
            opening = valve_open.get(b.valve_id, v["opening_pct"])
            req = max(nominal * pattern[step] * demand_factor * min(opening, 100.0) / 100.0, 0.0)
            if opening <= hy.CLOSED_VALVE_THRESHOLD_PCT:
                req = 0.0
            outlet_q[b.valve_id] = req
            out_outlets[b.valve_id]["demand"][step] = nominal * pattern[step] * demand_factor

        # --- 3. availability limiting (tanks processed upstream first) --------
        inlet_q = {}
        for tid in model.tank_order:
            cap = tanks[tid]["capacity_m3"]
            # inflows from upstream lines (already final)
            q_in_lines = sum(line_state[ln.pump_id]["q"] * (1 - line_state[ln.pump_id]["f_leak"])
                             for ln in lines_into[tid])
            q_out_req = sum(line_state[ln.pump_id]["q"] for ln in lines_from[tid]) + \
                sum(outlet_q[b.valve_id] for b in outlets_from[tid])
            # inlet supply: proportional level control around setpoint
            q_in_supply = 0.0
            for b in inlets_into[tid]:
                v = model.valves[b.valve_id]
                opening = valve_open.get(b.valve_id, v["opening_pct"])
                max_supply = v.get("boundary_flow_m3h") or 0.0
                sp = tanks[tid]["setpoint_pct"]
                share = 1.0 / len(inlets_into[tid])
                target = (q_out_req - q_in_lines) * share + INLET_LEVEL_GAIN_PER_H * (sp - level[tid]) / 100.0 * cap * share
                q_b = min(max(target, 0.0), max_supply) * (opening / 100.0)
                if opening <= hy.CLOSED_VALVE_THRESHOLD_PCT:
                    q_b = 0.0
                inlet_q[b.valve_id] = q_b
                q_in_supply += q_b
            available_vol = vol[tid] - MIN_TANK_VOLUME_FRACTION * cap + (q_in_lines + q_in_supply) * dt_h
            if q_out_req * dt_h > max(available_vol, 0.0) and q_out_req > 0:
                scale = max(available_vol, 0.0) / (q_out_req * dt_h)
                for ln in lines_from[tid]:
                    st = line_state[ln.pump_id]
                    st["q"] *= scale
                    st["starved"] = scale
                for b in outlets_from[tid]:
                    outlet_q[b.valve_id] *= scale

        # --- 4. record line results & pressures --------------------------------
        for ln in model.lines:
            st = line_state[ln.pump_id]
            pump = st["pump"]
            q = st["q"]
            q_down = q * (1 - st["f_leak"])
            o = out_lines[ln.pump_id]
            p_s = hy.head_to_bar(head_abs[ln.src_tank_id] - st["r_suc"] * q * q)
            if st["running"]:
                head = hy.pump_head(q, pump["shutoff_head_m"], pump["curve_k"], st["s"], st["hf"])
                if st.get("starved", 1.0) < 1.0:
                    head *= st["starved"]  # cavitation: head collapses when the pump runs dry
            else:
                head = 0.0
            p_d = p_s + hy.head_to_bar(head)
            last = ln.last_pipe_id
            r_last = model.element_resistance("PIPE", last) if last else 0.0
            p_down = hy.head_to_bar(head_abs[ln.dst_tank_id] + 0.5 * r_last * q_down * q_down)
            if not st["running"] or q <= 0:
                p_d = max(p_d, p_s)
            o["q_up"][step] = q
            o["q_down"][step] = q_down
            o["leak"][step] = q - q_down
            o["p_suction"][step] = p_s
            o["p_discharge"][step] = p_d
            o["p_down"][step] = p_down
            o["head"][step] = head
            o["running"][step] = 1.0 if st["running"] else 0.0
            o["speed_pct"][step] = st["s"] * 100.0
            o["health"][step] = st["hf"]
            o["efficiency"][step] = hy.pump_efficiency(q, pump["rated_flow_m3h"], pump["best_efficiency"], st["hf"])
            eff = o["efficiency"][step]
            o["power_kw"][step] = hy.hydraulic_power_kw(q, head) / eff if eff > 0.05 else 0.0

        for b in model.inlets:
            q = inlet_q.get(b.valve_id, 0.0)
            vmax = model.valves[b.valve_id].get("boundary_flow_m3h") or 1.0
            out_inlets[b.valve_id]["q"][step] = q
            out_inlets[b.valve_id]["p"][step] = SUPPLY_HEADER_BAR - 0.6 * (q / vmax) ** 2
        for b in model.outlets:
            out_outlets[b.valve_id]["q"][step] = outlet_q[b.valve_id]

        # --- 5. tank mass balance: V(t+1) = V(t) + (Qin - Qout - Qleak) dt ------
        for tid in tanks:
            # Qin is the flow entering the tank's inlet lines (measured upstream),
            # Qleak the part of it lost through pipe leaks before reaching the tank.
            q_in = sum(line_state[ln.pump_id]["q"] for ln in lines_into[tid]) + \
                sum(inlet_q.get(b.valve_id, 0.0) for b in inlets_into[tid])
            q_leak = sum(line_state[ln.pump_id]["q"] * line_state[ln.pump_id]["f_leak"] for ln in lines_into[tid])
            q_out = sum(line_state[ln.pump_id]["q"] for ln in lines_from[tid]) + \
                sum(outlet_q[b.valve_id] for b in outlets_from[tid])
            o = out_tanks[tid]
            o["volume_m3"][step] = vol[tid]
            o["level_pct"][step] = level[tid]
            o["inflow"][step] = q_in
            o["outflow"][step] = q_out
            o["leak_loss"][step] = q_leak
            new_v, overflow = hy.tank_volume_step(vol[tid], q_in, q_out, q_leak, dt_h, tanks[tid]["capacity_m3"])
            o["overflow_m3"][step] = overflow
            vol[tid] = new_v

    final_volume = {tid: vol[tid] for tid in tanks}
    return {
        "timestamps": timestamps,
        "step_minutes": step_minutes,
        "lines": out_lines,
        "tanks": out_tanks,
        "inlets": out_inlets,
        "outlets": out_outlets,
        "final_volume": final_volume,
    }


def true_value(result: dict, kind: str, key: str, qty: str) -> np.ndarray:
    bucket = {"LINE": "lines", "TANK": "tanks", "INLET": "inlets", "OUTLET": "outlets"}[kind]
    return result[bucket][key][qty]
