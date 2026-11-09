"""Process model: a structured view of a facility derived from equipment records.

The model is built from a plain, JSON-serialisable *configuration snapshot*
(dict of pumps/tanks/valves/pipes/sensors). The same builder is used by the
synthetic data generator, the simulation engine and the anomaly detector, so
all three share one interpretation of the plant.

Recognised structures (derived by walking the pipe graph, not hard-coded):

* Pump line:  TANK -> [pipes/valves] -> PUMP -> [pipes/valves] -> TANK
* Inlet:      INLET valve -> [pipe] -> TANK          (external supply boundary)
* Outlet:     TANK -> [pipe] -> OUTLET valve         (consumer demand boundary)
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Pipe, Pump, Sensor, Tank, Valve
from app.simulation import hydraulics as hy

PUMP_FIELDS = (
    "id", "name", "rated_flow_m3h", "shutoff_head_m", "curve_k", "speed_pct", "rated_power_kw",
    "best_efficiency", "health_factor", "available", "status",
)
TANK_FIELDS = (
    "id", "name", "capacity_m3", "height_m", "elevation_m", "initial_level_pct", "setpoint_pct",
    "high_alarm_pct", "low_alarm_pct", "status",
)
VALVE_FIELDS = ("id", "name", "valve_type", "role", "opening_pct", "resistance_full_open", "boundary_flow_m3h", "status")
PIPE_FIELDS = (
    "id", "name", "from_node_type", "from_node_id", "to_node_type", "to_node_id", "length_m", "diameter_mm",
    "friction_factor", "max_flow_m3h", "max_pressure_bar", "restriction_pct", "status",
)
SENSOR_FIELDS = (
    "id", "name", "tag", "equipment_type", "equipment_id", "sensor_type", "measurement_point", "unit",
    "min_range", "max_range", "accuracy_pct", "status",
)


def _row(obj: Any, fields: tuple[str, ...]) -> dict:
    return {f: getattr(obj, f) for f in fields}


def snapshot_from_objects(facility_id: str, pumps, tanks, valves, pipes, sensors) -> dict:
    return {
        "facility_id": facility_id,
        "pumps": {p.id: _row(p, PUMP_FIELDS) for p in sorted(pumps, key=lambda x: x.id)},
        "tanks": {t.id: _row(t, TANK_FIELDS) for t in sorted(tanks, key=lambda x: x.id)},
        "valves": {v.id: _row(v, VALVE_FIELDS) for v in sorted(valves, key=lambda x: x.id)},
        "pipes": {p.id: _row(p, PIPE_FIELDS) for p in sorted(pipes, key=lambda x: x.id)},
        "sensors": {s.id: _row(s, SENSOR_FIELDS) for s in sorted(sensors, key=lambda x: x.id)},
    }


def snapshot_from_db(db: Session, facility_id: str) -> dict:
    def q(model):
        return db.scalars(select(model).where(model.facility_id == facility_id)).all()

    return snapshot_from_objects(facility_id, q(Pump), q(Tank), q(Valve), q(Pipe), q(Sensor))


@dataclass
class PumpLine:
    pump_id: str
    src_tank_id: str
    dst_tank_id: str
    suction_path: list[tuple[str, str]]  # ordered (kind, id) from src tank to pump
    discharge_path: list[tuple[str, str]]  # ordered (kind, id) from pump to dst tank
    sensors: dict[str, str] = field(default_factory=dict)  # role -> sensor id

    @property
    def pipe_ids(self) -> list[str]:
        return [i for k, i in self.suction_path + self.discharge_path if k == "PIPE"]

    @property
    def valve_ids(self) -> list[str]:
        return [i for k, i in self.suction_path + self.discharge_path if k == "VALVE"]

    @property
    def discharge_pipe_ids(self) -> list[str]:
        return [i for k, i in self.discharge_path if k == "PIPE"]

    @property
    def last_pipe_id(self) -> str | None:
        d = self.discharge_pipe_ids
        return d[-1] if d else None


@dataclass
class Boundary:
    kind: str  # INLET / OUTLET
    valve_id: str
    tank_id: str
    pipe_ids: list[str]
    sensors: dict[str, str] = field(default_factory=dict)


@dataclass
class ProcessModel:
    config: dict
    lines: list[PumpLine]
    inlets: list[Boundary]
    outlets: list[Boundary]
    tank_order: list[str]
    issues: list[dict]
    sensor_map: dict[str, tuple[str, str, str]]  # sensor id -> (structure kind, structure key, quantity)

    @property
    def facility_id(self) -> str:
        return self.config["facility_id"]

    @property
    def tanks(self) -> dict:
        return self.config["tanks"]

    @property
    def pumps(self) -> dict:
        return self.config["pumps"]

    @property
    def valves(self) -> dict:
        return self.config["valves"]

    @property
    def pipes(self) -> dict:
        return self.config["pipes"]

    @property
    def sensors(self) -> dict:
        return self.config["sensors"]

    def line_for_pump(self, pump_id: str) -> PumpLine | None:
        return next((ln for ln in self.lines if ln.pump_id == pump_id), None)

    def line_for_pipe(self, pipe_id: str) -> PumpLine | None:
        return next((ln for ln in self.lines if pipe_id in ln.pipe_ids), None)

    # ---- resistances ----------------------------------------------------
    def element_resistance(self, kind: str, eid: str, restrictions: dict | None = None,
                           valve_openings: dict | None = None) -> float:
        if kind == "PIPE":
            p = self.pipes[eid]
            r = hy.pipe_resistance(p["length_m"], p["diameter_mm"], p["friction_factor"])
            restr = p["restriction_pct"]
            if restrictions and eid in restrictions:
                restr = max(restr, restrictions[eid])
            if restr > 0:
                # A restriction acts as a local contraction loss on top of friction.
                r = r + hy.restricted_resistance(r * 4.0, restr) - r * 4.0
            return r
        v = self.valves[eid]
        opening = v["opening_pct"]
        if valve_openings and eid in valve_openings:
            opening = valve_openings[eid]
        return hy.valve_resistance(v["resistance_full_open"], opening)

    def line_resistances(self, line: PumpLine, restrictions: dict | None = None,
                         valve_openings: dict | None = None, leak_pipe: str | None = None) -> tuple[float, float, float]:
        """Returns (R_suction, R_up, R_down). R_up covers the discharge path up
        to the middle of the leaking pipe; R_down the remainder (carries the
        reduced, post-leak flow). Without a leak R_down = 0."""
        r_suc = sum(self.element_resistance(k, i, restrictions, valve_openings) for k, i in line.suction_path)
        r_up = 0.0
        r_down = 0.0
        past_leak = False
        for k, i in line.discharge_path:
            r = self.element_resistance(k, i, restrictions, valve_openings)
            if leak_pipe is not None and k == "PIPE" and i == leak_pipe:
                r_up += r / 2
                r_down += r / 2
                past_leak = True
            elif past_leak:
                r_down += r
            else:
                r_up += r
        return r_suc, r_up, r_down


def _walk(adj_pipes: dict[str, list[dict]], start: str, node_type: dict[str, str], direction: str,
          stop_types: tuple[str, ...]) -> tuple[list[tuple[str, str]], str | None, list[str]]:
    """Follow single pipes from ``start`` until a node of ``stop_types`` is reached."""
    path: list[tuple[str, str]] = []
    issues: list[str] = []
    node = start
    visited = {start}
    while True:
        pipes = adj_pipes.get(node, [])
        if not pipes:
            return path, None, issues
        if len(pipes) > 1:
            issues.append(f"{node} has {len(pipes)} {direction} pipes; using {pipes[0]['id']}")
        pipe = pipes[0]
        nxt = pipe["to_node_id"] if direction == "downstream" else pipe["from_node_id"]
        if nxt in visited:
            issues.append(f"Loop detected at {nxt}")
            return path, None, issues
        visited.add(nxt)
        path.append(("PIPE", pipe["id"]))
        t = node_type.get(nxt)
        if t is None:
            issues.append(f"Pipe {pipe['id']} references missing node {nxt}")
            return path, None, issues
        if t in stop_types:
            return path, nxt, issues
        if t == "VALVE":
            path.append(("VALVE", nxt))
            node = nxt
            continue
        issues.append(f"Unexpected node {nxt} ({t}) while walking {direction} from {start}")
        return path, None, issues


def build_process_model(config: dict) -> ProcessModel:
    cfg = config
    node_type: dict[str, str] = {}
    for pid in cfg["pumps"]:
        node_type[pid] = "PUMP"
    for tid in cfg["tanks"]:
        node_type[tid] = "TANK"
    for vid in cfg["valves"]:
        node_type[vid] = "VALVE"

    out_adj: dict[str, list[dict]] = {}
    in_adj: dict[str, list[dict]] = {}
    for p in sorted(cfg["pipes"].values(), key=lambda x: x["id"]):
        if p.get("status", "IN_SERVICE") != "IN_SERVICE":
            continue
        out_adj.setdefault(p["from_node_id"], []).append(p)
        in_adj.setdefault(p["to_node_id"], []).append(p)

    issues: list[dict] = []
    lines: list[PumpLine] = []
    for pid in sorted(cfg["pumps"]):
        up_path, src, up_issues = _walk(in_adj, pid, node_type, "upstream", ("TANK", "PUMP"))
        dn_path, dst, dn_issues = _walk(out_adj, pid, node_type, "downstream", ("TANK", "PUMP"))
        for msg in up_issues + dn_issues:
            issues.append({"equipment_id": pid, "issue": msg})
        if src is None or dst is None or node_type.get(src) != "TANK" or node_type.get(dst) != "TANK":
            issues.append({"equipment_id": pid, "issue": "Pump is not part of a complete TANK->PUMP->TANK line; "
                           "excluded from hydraulic calculation"})
            continue
        lines.append(PumpLine(pid, src, dst, list(reversed(up_path)), dn_path))

    inlets: list[Boundary] = []
    outlets: list[Boundary] = []
    for vid, v in sorted(cfg["valves"].items()):
        if v["role"] == "INLET":
            path, tank, iss = _walk(out_adj, vid, node_type, "downstream", ("TANK",))
            if tank:
                inlets.append(Boundary("INLET", vid, tank, [i for k, i in path if k == "PIPE"]))
            else:
                issues.append({"equipment_id": vid, "issue": "Inlet valve does not reach a tank; " + "; ".join(iss)})
        elif v["role"] == "OUTLET":
            path, tank, iss = _walk(in_adj, vid, node_type, "upstream", ("TANK",))
            if tank:
                outlets.append(Boundary("OUTLET", vid, tank, [i for k, i in path if k == "PIPE"]))
            else:
                issues.append({"equipment_id": vid, "issue": "Outlet valve is not fed by a tank; " + "; ".join(iss)})

    # Topological order of tanks (upstream first) using pump lines
    order: list[str] = []
    indeg = {t: 0 for t in cfg["tanks"]}
    succ: dict[str, list[str]] = {t: [] for t in cfg["tanks"]}
    for ln in lines:
        succ[ln.src_tank_id].append(ln.dst_tank_id)
        indeg[ln.dst_tank_id] += 1
    ready = sorted(t for t, d in indeg.items() if d == 0)
    while ready:
        t = ready.pop(0)
        order.append(t)
        for s in succ[t]:
            indeg[s] -= 1
            if indeg[s] == 0:
                ready.append(s)
                ready.sort()
    for t in sorted(cfg["tanks"]):
        if t not in order:
            order.append(t)
            issues.append({"equipment_id": t, "issue": "Tank participates in a pumping cycle"})

    # Sensor mapping
    sensor_map: dict[str, tuple[str, str, str]] = {}
    last_pipe_to_line = {ln.last_pipe_id: ln for ln in lines if ln.last_pipe_id}
    pump_to_line = {ln.pump_id: ln for ln in lines}
    inlet_by_valve = {b.valve_id: b for b in inlets}
    outlet_by_valve = {b.valve_id: b for b in outlets}
    for sid, s in sorted(cfg["sensors"].items()):
        et, eid, st, mp = s["equipment_type"], s["equipment_id"], s["sensor_type"], s["measurement_point"]
        target = None
        if et == "PUMP" and eid in pump_to_line:
            ln = pump_to_line[eid]
            if st == "FLOW":
                target, ln.sensors["flow_up"] = ("LINE", eid, "q_up"), sid
            elif st == "PRESSURE" and mp == "SUCTION":
                target, ln.sensors["p_suction"] = ("LINE", eid, "p_suction"), sid
            elif st == "PRESSURE":
                target, ln.sensors["p_discharge"] = ("LINE", eid, "p_discharge"), sid
        elif et == "PIPE" and eid in last_pipe_to_line:
            ln = last_pipe_to_line[eid]
            if st == "FLOW":
                target, ln.sensors["flow_down"] = ("LINE", ln.pump_id, "q_down"), sid
            elif st == "PRESSURE":
                target, ln.sensors["p_down"] = ("LINE", ln.pump_id, "p_down"), sid
        elif et == "TANK" and st == "LEVEL" and eid in cfg["tanks"]:
            target = ("TANK", eid, "level_pct")
        elif et == "VALVE" and eid in inlet_by_valve:
            b = inlet_by_valve[eid]
            if st == "FLOW":
                target, b.sensors["flow"] = ("INLET", eid, "q"), sid
            elif st == "PRESSURE":
                target, b.sensors["pressure"] = ("INLET", eid, "p"), sid
        elif et == "VALVE" and eid in outlet_by_valve:
            b = outlet_by_valve[eid]
            if st == "FLOW":
                target, b.sensors["flow"] = ("OUTLET", eid, "q"), sid
        if target:
            sensor_map[sid] = target
        else:
            issues.append({"equipment_id": sid, "issue": f"Sensor at {et} {eid} ({st}/{mp}) is not mapped to a "
                           "modelled quantity; no readings simulated"})

    return ProcessModel(copy.deepcopy(cfg), lines, inlets, outlets, order, issues, sensor_map)


def tank_level_sensor(model: ProcessModel, tank_id: str) -> str | None:
    for sid, (kind, key, _qty) in model.sensor_map.items():
        if kind == "TANK" and key == tank_id:
            return sid
    return None
