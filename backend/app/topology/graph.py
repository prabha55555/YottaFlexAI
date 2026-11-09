"""Industrial network topology built with NetworkX from database records.

Nodes: pumps, tanks, valves. Directed edges: pipes (flow direction from -> to).
Validation covers missing nodes, cross-facility pipes, self loops, duplicate
connections, role/degree rules, isolated nodes, cycles, connected components
and reachability from supply (INLET) to demand (OUTLET) boundaries.
"""
from __future__ import annotations

from collections import defaultdict

import networkx as nx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Alarm, Pipe, Pump, Sensor, Tank, Valve

ROLE_RULES = {
    # node kind -> (min_in, max_in, min_out, max_out); None = unbounded
    "PUMP": (1, 1, 1, 1),
    "VALVE:INLINE": (1, 1, 1, 1),
    "VALVE:INLET": (0, 0, 1, 1),
    "VALVE:OUTLET": (1, 1, 0, 0),
    "TANK": (0, None, 0, None),
}


def build_graph(nodes: list[dict], pipes: list[dict]) -> tuple[nx.DiGraph, list[dict]]:
    """Build a DiGraph; returns (graph, issues found while adding edges)."""
    g = nx.DiGraph()
    issues: list[dict] = []
    for n in nodes:
        g.add_node(n["id"], **n)
    seen = set()
    for p in pipes:
        a, b = p["from_node_id"], p["to_node_id"]
        if a not in g or b not in g:
            missing = [x for x in (a, b) if x not in g]
            issues.append({"severity": "ERROR", "code": "MISSING_NODE", "equipment_id": p["id"],
                           "message": f"Pipe {p['id']} references missing node(s): {', '.join(missing)}."})
            continue
        if a == b:
            issues.append({"severity": "ERROR", "code": "SELF_LOOP", "equipment_id": p["id"],
                           "message": f"Pipe {p['id']} starts and ends at {a}."})
            continue
        if g.nodes[a]["facility_id"] != p["facility_id"] or g.nodes[b]["facility_id"] != p["facility_id"]:
            issues.append({"severity": "ERROR", "code": "CROSS_FACILITY", "equipment_id": p["id"],
                           "message": f"Pipe {p['id']} connects nodes from different facilities."})
        if (a, b) in seen:
            issues.append({"severity": "ERROR", "code": "DUPLICATE_CONNECTION", "equipment_id": p["id"],
                           "message": f"Duplicate pipe between {a} and {b}."})
            continue
        if g.nodes[a].get("node_type") != p.get("from_node_type") or g.nodes[b].get("node_type") != p.get("to_node_type"):
            issues.append({"severity": "ERROR", "code": "NODE_TYPE_MISMATCH", "equipment_id": p["id"],
                           "message": f"Pipe {p['id']} declares node types {p.get('from_node_type')}->"
                                      f"{p.get('to_node_type')} but nodes are {g.nodes[a].get('node_type')}->"
                                      f"{g.nodes[b].get('node_type')}."})
        seen.add((a, b))
        g.add_edge(a, b, **p)
    return g, issues


def analyse_graph(g: nx.DiGraph) -> dict:
    issues: list[dict] = []
    for nid, d in g.nodes(data=True):
        kind = d["node_type"] if d["node_type"] != "VALVE" else f"VALVE:{d.get('role', 'INLINE')}"
        rule = ROLE_RULES.get(kind)
        if rule is None:
            continue
        indeg, outdeg = g.in_degree(nid), g.out_degree(nid)
        mi, ma, mo, mx = rule
        if indeg == 0 and outdeg == 0:
            issues.append({"severity": "ERROR", "code": "ISOLATED_NODE", "equipment_id": nid,
                           "message": f"{nid} has no pipe connections."})
            continue
        if indeg < mi or (ma is not None and indeg > ma):
            issues.append({"severity": "ERROR", "code": "INVALID_INLET_COUNT", "equipment_id": nid,
                           "message": f"{kind} {nid} has {indeg} incoming pipe(s); expected {mi}"
                                      f"{'' if ma == mi else '..' + str(ma if ma is not None else 'n')}."})
        if outdeg < mo or (mx is not None and outdeg > mx):
            issues.append({"severity": "ERROR", "code": "INVALID_OUTLET_COUNT", "equipment_id": nid,
                           "message": f"{kind} {nid} has {outdeg} outgoing pipe(s); expected {mo}"
                                      f"{'' if mx == mo else '..' + str(mx if mx is not None else 'n')}."})
    # Flow-direction rules: pumps must draw from tank/valve and discharge to valve/tank
    for a, b, d in g.edges(data=True):
        ta, tb = g.nodes[a]["node_type"], g.nodes[b]["node_type"]
        if ta == "PUMP" and tb == "PUMP":
            issues.append({"severity": "WARNING", "code": "PUMPS_IN_SERIES", "equipment_id": d["id"],
                           "message": f"Pipe {d['id']} connects two pumps directly ({a}->{b})."})
        if g.nodes[b].get("role") == "INLET":
            issues.append({"severity": "ERROR", "code": "FLOW_INTO_INLET", "equipment_id": d["id"],
                           "message": f"Pipe {d['id']} flows into supply boundary valve {b}."})
        if g.nodes[a].get("role") == "OUTLET":
            issues.append({"severity": "ERROR", "code": "FLOW_FROM_OUTLET", "equipment_id": d["id"],
                           "message": f"Pipe {d['id']} flows out of demand boundary valve {a}."})

    cycles = []
    try:
        cycles = [c for c in nx.simple_cycles(g)][:10]
    except nx.NetworkXException:
        pass
    for c in cycles:
        issues.append({"severity": "WARNING", "code": "FLOW_CYCLE", "equipment_id": c[0],
                       "message": f"Directed cycle: {' -> '.join(c + [c[0]])}."})

    components = [sorted(c) for c in nx.weakly_connected_components(g)]
    components.sort(key=lambda c: c[0])
    sources = sorted(n for n, d in g.nodes(data=True) if d.get("role") == "INLET")
    sinks = sorted(n for n, d in g.nodes(data=True) if d.get("role") == "OUTLET")
    reachable = set()
    for s in sources:
        reachable |= nx.descendants(g, s) | {s}
    unreachable = sorted(n for n in g.nodes if n not in reachable)
    for n in unreachable:
        if g.degree(n) > 0:
            issues.append({"severity": "WARNING", "code": "UNREACHABLE_FROM_SUPPLY", "equipment_id": n,
                           "message": f"{n} cannot be reached from any supply inlet."})
    can_drain = set()
    for t in sinks:
        can_drain |= nx.ancestors(g, t) | {t}
    dead_ends = sorted(n for n in g.nodes if n not in can_drain and g.degree(n) > 0)
    for n in dead_ends:
        issues.append({"severity": "WARNING", "code": "NO_PATH_TO_DEMAND", "equipment_id": n,
                       "message": f"No flow path from {n} to any demand outlet."})
    paths = []
    for s in sources:
        for t in sinks:
            if nx.has_path(g, s, t):
                paths.append({"source": s, "sink": t, "path": nx.shortest_path(g, s, t)})
    errors = sum(1 for i in issues if i["severity"] == "ERROR")
    return {
        "is_valid": errors == 0,
        "error_count": errors,
        "warning_count": sum(1 for i in issues if i["severity"] == "WARNING"),
        "issues": issues,
        "components": [{"id": i + 1, "nodes": c, "size": len(c)} for i, c in enumerate(components)],
        "is_dag": nx.is_directed_acyclic_graph(g),
        "sources": sources,
        "sinks": sinks,
        "unreachable_nodes": unreachable,
        "supply_to_demand_paths": paths,
    }


def layout(g: nx.DiGraph, components: list[list[str]]) -> dict[str, dict]:
    """Left-to-right layered layout: x = longest-path depth, y = component band."""
    pos: dict[str, dict] = {}
    y_offset = 0.0
    for comp in components:
        sub = g.subgraph(comp)
        if nx.is_directed_acyclic_graph(sub):
            depth = {}
            for n in nx.topological_sort(sub):
                preds = list(sub.predecessors(n))
                depth[n] = 0 if not preds else max(depth[p] + 1 for p in preds)
        else:
            depth = {n: i for i, n in enumerate(sorted(comp))}
        by_depth = defaultdict(list)
        for n, d in depth.items():
            by_depth[d].append(n)
        max_rows = max(len(v) for v in by_depth.values())
        for d, ns in by_depth.items():
            for r, n in enumerate(sorted(ns)):
                pos[n] = {"x": d * 150.0, "y": y_offset + r * 110.0}
        y_offset += max_rows * 110.0 + 70.0
    return pos


def facility_topology(db: Session, facility_id: str, include_sim_alarms: bool = False) -> dict:
    def q(model):
        return db.scalars(select(model).where(model.facility_id == facility_id).order_by(model.id)).all()

    pumps, tanks, valves, pipes, sensors = q(Pump), q(Tank), q(Valve), q(Pipe), q(Sensor)
    alarm_q = select(Alarm).where(Alarm.facility_id == facility_id, Alarm.status.in_(("ACTIVE", "ACKNOWLEDGED")))
    if not include_sim_alarms:
        alarm_q = alarm_q.where(Alarm.simulation_id.is_(None))
    alarms = db.scalars(alarm_q).all()
    sev_rank = {"LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}
    alarm_by_eq: dict[str, list] = defaultdict(list)
    for a in alarms:
        alarm_by_eq[a.equipment_id].append(a)
    sensors_by_eq: dict[str, list] = defaultdict(list)
    for s in sensors:
        sensors_by_eq[s.equipment_id].append(s)

    def health(eid: str) -> tuple[str, int, str | None]:
        al = alarm_by_eq.get(eid, [])
        if not al:
            return "NORMAL", 0, None
        top = max(al, key=lambda a: sev_rank[a.severity]).severity
        return ("CRITICAL" if top in ("CRITICAL", "HIGH") else "WARNING"), len(al), top

    nodes = []
    for p in pumps:
        nodes.append({"id": p.id, "node_type": "PUMP", "facility_id": p.facility_id, "name": p.name,
                      "status": p.status, "details": {"rated_flow_m3h": p.rated_flow_m3h, "speed_pct": p.speed_pct,
                                                      "health_factor": p.health_factor, "available": p.available,
                                                      "shutoff_head_m": round(p.shutoff_head_m, 2)}})
    for t in tanks:
        nodes.append({"id": t.id, "node_type": "TANK", "facility_id": t.facility_id, "name": t.name,
                      "status": t.status, "details": {"capacity_m3": t.capacity_m3, "height_m": t.height_m,
                                                      "elevation_m": t.elevation_m,
                                                      "high_alarm_pct": t.high_alarm_pct}})
    for v in valves:
        nodes.append({"id": v.id, "node_type": "VALVE", "role": v.role, "facility_id": v.facility_id, "name": v.name,
                      "status": v.status, "details": {"opening_pct": v.opening_pct, "valve_type": v.valve_type,
                                                      "role": v.role, "boundary_flow_m3h": v.boundary_flow_m3h}})
    pipe_dicts = [{"id": p.id, "facility_id": p.facility_id, "name": p.name, "from_node_id": p.from_node_id,
                   "to_node_id": p.to_node_id, "from_node_type": p.from_node_type, "to_node_type": p.to_node_type,
                   "length_m": p.length_m, "diameter_mm": p.diameter_mm, "max_flow_m3h": p.max_flow_m3h,
                   "max_pressure_bar": p.max_pressure_bar, "restriction_pct": p.restriction_pct, "status": p.status}
                  for p in pipes]
    g, edge_issues = build_graph(nodes, pipe_dicts)
    analysis = analyse_graph(g)
    analysis["issues"] = edge_issues + analysis["issues"]
    analysis["error_count"] += sum(1 for i in edge_issues if i["severity"] == "ERROR")
    analysis["is_valid"] = analysis["error_count"] == 0
    pos = layout(g, [c["nodes"] for c in analysis["components"]])
    issue_ids = {i["equipment_id"] for i in analysis["issues"] if i["severity"] == "ERROR"}

    out_nodes = []
    for n in nodes:
        h, count, top = health(n["id"])
        if n["id"] in issue_ids:
            h = "CRITICAL" if h == "NORMAL" else h
        out_nodes.append({**n, "position": pos.get(n["id"], {"x": 0, "y": 0}), "health": h, "active_alarms": count,
                          "top_severity": top,
                          "sensors": [{"id": s.id, "tag": s.tag, "sensor_type": s.sensor_type, "unit": s.unit,
                                       "measurement_point": s.measurement_point} for s in sensors_by_eq.get(n["id"], [])]})
    edges = []
    for p in pipe_dicts:
        h, count, top = health(p["id"])
        edges.append({**p, "source": p["from_node_id"], "target": p["to_node_id"], "health": h,
                      "active_alarms": count, "top_severity": top,
                      "valid": p["from_node_id"] in g and p["to_node_id"] in g,
                      "sensors": [{"id": s.id, "tag": s.tag, "sensor_type": s.sensor_type, "unit": s.unit}
                                  for s in sensors_by_eq.get(p["id"], [])]})
    return {"facility_id": facility_id, "nodes": out_nodes, "edges": edges,
            "summary": {"nodes": g.number_of_nodes(), "edges": g.number_of_edges(), "pumps": len(pumps),
                        "tanks": len(tanks), "valves": len(valves), "pipes": len(pipes), "sensors": len(sensors)},
            "validation": analysis}
