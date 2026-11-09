"""Deterministic master-data layout.

Each facility is organised in *process trains*:

    INLET valve -> Tank(stage 0) -> [suction valve -> pump -> discharge valve] -> Tank(stage 1) -> ... -> OUTLET valve

Pumps are sized so that, at 50 % tank levels and the configured discharge
valve opening, every pump in a train delivers the train design flow
(calibrated duty point on its H(Q) = s^2 H0 - k Q^2 curve).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from app.simulation import hydraulics as hy

FACILITY_SPECS = [
    {"name": "North Water Treatment Plant", "location": "Riverside District", "trains": [4, 3, 3],
     "description": "Raw water intake, clarification and treated-water storage."},
    {"name": "East Process Facility", "location": "Industrial Zone East", "trains": [4, 3, 3],
     "description": "Process water conditioning and transfer to production lines."},
    {"name": "South Distribution Hub", "location": "Southern Corridor", "trains": [3, 3, 2, 2],
     "description": "Bulk storage and pumped distribution to consumer networks."},
]

OPERATING_MODES = [
    ("MODE-001", "NORMAL", "Normal operation at design demand.", 1.0, 1.0),
    ("MODE-002", "HIGH_DEMAND", "Peak consumer demand (+40 %).", 1.4, 1.0),
    ("MODE-003", "LOW_DEMAND", "Night / low demand operation.", 0.6, 0.95),
    ("MODE-004", "MAINTENANCE", "Reduced throughput during maintenance works.", 0.5, 0.9),
    ("MODE-005", "EMERGENCY_SUPPLY", "Emergency supply with pumps at maximum speed.", 1.6, 1.05),
]

STAGE_NAMES = ["Raw Water Tank", "Clarified Water Tank", "Filtered Water Tank", "Product Storage Tank"]
STANDARD_DIAMETERS_MM = [100, 125, 150, 200, 250, 300, 350, 400]


def fid(prefix: str, n: int, width: int = 3) -> str:
    return f"{prefix}-{n:0{width}d}"


def pick_diameter(q_m3h: float, velocity: float = 1.6) -> int:
    d = math.sqrt(4 * (q_m3h / 3600) / (math.pi * velocity)) * 1000
    for std in STANDARD_DIAMETERS_MM:
        if std >= d:
            return std
    return STANDARD_DIAMETERS_MM[-1]


def max_flow_for(d_mm: int, v_max: float = 3.0) -> float:
    return round(math.pi / 4 * (d_mm / 1000) ** 2 * v_max * 3600, 1)


def round_up(x: float, step: float) -> float:
    return math.ceil(x / step) * step


@dataclass
class Rec:
    """Plain attribute container used before rows are written to the database."""

    def __init__(self, **kw):
        self.__dict__.update(kw)

    def as_dict(self) -> dict:
        return dict(self.__dict__)


def build_master_data(rng: np.random.Generator) -> dict[str, list[Rec]]:
    facilities, pumps, tanks, valves, pipes, sensors, modes = [], [], [], [], [], [], []
    for mid, name, desc, df, sf in OPERATING_MODES:
        modes.append(Rec(id=mid, name=name, description=desc, demand_factor=df, pump_speed_factor=sf))

    c = {"pump": 0, "tank": 0, "valve": 0, "pipe": 0, "sensor": 0}

    def nxt(kind: str) -> int:
        c[kind] += 1
        return c[kind]

    for f_idx, spec in enumerate(FACILITY_SPECS, start=1):
        fac_id = fid("FAC", f_idx)
        facilities.append(Rec(id=fac_id, name=spec["name"], location=spec["location"], description=spec["description"],
                              status="OPERATIONAL", operating_mode_id="MODE-001"))
        tag_seq = {"FT": 0, "PT": 0, "LT": 0}

        # Helpers bind the current facility explicitly (default args) so they never
        # capture a later loop iteration's values.
        def add_sensor(eq_type, eq_id, s_type, point, unit, lo, hi, acc, label,
                       fac_id=fac_id, f_idx=f_idx, tag_seq=tag_seq):
            prefix = {"FLOW": "FT", "PRESSURE": "PT", "LEVEL": "LT"}[s_type]
            tag_seq[prefix] += 1
            sid = fid("SNS", nxt("sensor"))
            sensors.append(Rec(id=sid, facility_id=fac_id, name=label, tag=f"{prefix}-{f_idx}{tag_seq[prefix]:02d}",
                               equipment_type=eq_type, equipment_id=eq_id, sensor_type=s_type, measurement_point=point,
                               unit=unit, min_range=lo, max_range=hi, accuracy_pct=acc, status="ACTIVE"))

        def add_pipe(name, ft, fid_, tt, tid_, length, dia, pmax, fac_id=fac_id):
            pid = fid("PIPE", nxt("pipe"))
            pipes.append(Rec(id=pid, facility_id=fac_id, name=name, from_node_type=ft, from_node_id=fid_,
                             to_node_type=tt, to_node_id=tid_, length_m=round(length, 1), diameter_mm=float(dia),
                             friction_factor=0.02, max_flow_m3h=max_flow_for(dia), max_pressure_bar=pmax,
                             restriction_pct=0.0, status="IN_SERVICE"))
            return pid

        def add_valve(name, vtype, role, opening, r100, boundary=None, fac_id=fac_id):
            vid = fid("VALVE", nxt("valve"))
            valves.append(Rec(id=vid, facility_id=fac_id, name=name, valve_type=vtype, role=role,
                              opening_pct=opening, resistance_full_open=r100, boundary_flow_m3h=boundary,
                              status="IN_SERVICE"))
            return vid

        for t_idx, n_tanks in enumerate(spec["trains"]):
            train = chr(ord("A") + t_idx)
            q_design = round(float(rng.uniform(60, 160)), 1)
            dia = pick_diameter(q_design)
            flow_range = round_up(2.0 * q_design, 50)
            train_tanks = []
            for st in range(n_tanks):
                tank_id = fid("TANK", nxt("tank"))
                height = round(float(rng.uniform(6.0, 10.0)), 2)
                capacity = round(float(q_design * rng.uniform(9.0, 14.0)), 0)
                elevation = round(2.0 + 7.0 * st + float(rng.uniform(0.0, 1.5)), 2)
                stage_name = STAGE_NAMES[min(st, len(STAGE_NAMES) - 1)] if st < n_tanks - 1 else STAGE_NAMES[-1]
                tanks.append(Rec(id=tank_id, facility_id=fac_id, name=f"{stage_name} {train}{st + 1}",
                                 capacity_m3=capacity, height_m=height, elevation_m=elevation,
                                 initial_level_pct=50.0, setpoint_pct=50.0, high_alarm_pct=95.0, low_alarm_pct=10.0,
                                 status="IN_SERVICE"))
                train_tanks.append(tanks[-1])
                add_sensor("TANK", tank_id, "LEVEL", "LEVEL", "%", 0.0, 100.0, 0.25, f"Level {tank_id}")

            # Inlet boundary
            r100_in = 0.4 / q_design**2
            v_in = add_valve(f"Inlet Control Valve {train}", "CONTROL", "INLET", 100.0, r100_in,
                             boundary=round(1.8 * q_design, 1))
            add_pipe(f"Supply Main {train}", "VALVE", v_in, "TANK", train_tanks[0].id,
                     float(rng.uniform(30, 80)), dia, 10.0)
            add_sensor("VALVE", v_in, "FLOW", "INLET", "m3/h", 0.0, round_up(2.0 * 1.8 * q_design, 50), 0.5,
                       f"Supply flow {train}")
            add_sensor("VALVE", v_in, "PRESSURE", "INLET", "bar", 0.0, 6.0, 0.5, f"Supply pressure {train}")

            # Pump lines
            for st in range(n_tanks - 1):
                src, dst = train_tanks[st], train_tanks[st + 1]
                stage = f"{train}{st + 1}"
                r100_iso = 0.15 / q_design**2
                r100_ctl = 0.5 / q_design**2
                open_ctl = round(float(rng.uniform(65, 85)), 1)
                v_s = add_valve(f"Suction Isolation Valve {stage}", "GATE", "INLINE", 100.0, r100_iso)
                v_d = add_valve(f"Discharge Control Valve {stage}", "GLOBE", "INLINE", open_ctl, r100_ctl)
                pump_id = fid("PUMP", c["pump"] + 1)
                l_s1, l_s2 = float(rng.uniform(5, 15)), float(rng.uniform(2, 5))
                l_d1, l_tr = float(rng.uniform(3, 8)), float(rng.uniform(150, 450))
                p1 = add_pipe(f"Suction Line {stage}a", "TANK", src.id, "VALVE", v_s, l_s1, dia, 6.0)
                p2 = add_pipe(f"Suction Line {stage}b", "VALVE", v_s, "PUMP", pump_id, l_s2, dia, 6.0)
                p3 = add_pipe(f"Discharge Spool {stage}", "PUMP", pump_id, "VALVE", v_d, l_d1, dia, 10.0)
                p4 = add_pipe(f"Transfer Main {stage}", "VALVE", v_d, "TANK", dst.id, l_tr, dia, 10.0)

                # Calibrate pump duty point at 50 % levels
                hs = (dst.elevation_m + 0.5 * dst.height_m) - (src.elevation_m + 0.5 * src.height_m)
                r_pipes = sum(hy.pipe_resistance(L, dia, 0.02) for L in (l_s1, l_s2, l_d1, l_tr))
                r_valves = hy.valve_resistance(r100_iso, 100.0) + hy.valve_resistance(r100_ctl, open_ctl)
                h_req = hs + (r_pipes + r_valves) * q_design**2
                alpha = float(rng.uniform(0.22, 0.35))
                k = alpha * h_req / q_design**2
                speed = float(rng.choice([90.0, 95.0, 100.0]))
                s = speed / 100
                h0 = (h_req + k * q_design**2) / s**2
                eta = round(float(rng.uniform(0.70, 0.82)), 3)
                power = hy.hydraulic_power_kw(q_design * 1.2, h0) / eta
                nxt("pump")
                pumps.append(Rec(id=pump_id, facility_id=fac_id, name=f"Transfer Pump {stage}",
                                 rated_flow_m3h=round(q_design * float(rng.uniform(1.05, 1.15)), 1),
                                 shutoff_head_m=round(h0, 4), curve_k=float(f"{k:.6e}"), speed_pct=speed,
                                 rated_power_kw=round(round_up(power, 5), 1), best_efficiency=eta, health_factor=1.0,
                                 available=True, status="RUNNING"))
                pd_range = 10.0
                add_sensor("PUMP", pump_id, "FLOW", "DISCHARGE", "m3/h", 0.0, flow_range, 0.5,
                           f"Discharge flow {pump_id}")
                add_sensor("PUMP", pump_id, "PRESSURE", "DISCHARGE", "bar", 0.0, pd_range, 0.25,
                           f"Discharge pressure {pump_id}")
                add_sensor("PUMP", pump_id, "PRESSURE", "SUCTION", "bar", 0.0, 6.0, 0.25,
                           f"Suction pressure {pump_id}")
                add_sensor("PIPE", p4, "FLOW", "OUTLET_END", "m3/h", 0.0, flow_range, 0.5, f"Delivered flow {p4}")
                add_sensor("PIPE", p4, "PRESSURE", "OUTLET_END", "bar", 0.0, 6.0, 0.25, f"Delivery pressure {p4}")
                _ = (p1, p2, p3)

            # Outlet boundary
            last = train_tanks[-1]
            v_out = add_valve(f"Outlet Valve {train}", "BUTTERFLY", "OUTLET", 100.0, 0.3 / q_design**2,
                              boundary=q_design)
            add_pipe(f"Distribution Main {train}", "TANK", last.id, "VALVE", v_out, float(rng.uniform(50, 150)),
                     pick_diameter(q_design, 1.4), 6.0)
            add_sensor("VALVE", v_out, "FLOW", "OUTLET", "m3/h", 0.0, flow_range, 0.5, f"Demand flow {train}")

    return {"operating_modes": modes, "facilities": facilities, "pumps": pumps, "tanks": tanks,
            "valves": valves, "pipes": pipes, "sensors": sensors}
