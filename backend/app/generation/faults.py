"""Scenario (fault) injection rules and ground-truth label generation.

Injection rules (documented in docs/SIMULATION_ASSUMPTIONS.md):

* Per facility, three *different* pump lines receive one process fault each:
  PIPE_LEAK on the transfer main (8-20 % of line flow), PIPE_BLOCKAGE on the
  transfer main (40-65 % area restriction) and PUMP_DEGRADATION (health 0.68-0.85).
* Per facility, three sensor faults on sensors that are not on faulted lines.
  Modes rotate through FLATLINE, SPIKE, OUT_OF_RANGE, MISSING, BIAS so every
  mode occurs at least once in the dataset; BIAS is always applied to a pipe-end
  flow meter (the classic "looks like a leak" case).
* One facility gets an operator event that throttles an outlet valve to 15 %,
  driving the end tank to overcapacity.

Ground-truth labels are produced from these rules and from the *true* process
state (e.g. tank overcapacity intervals = true level >= 95 %), never from the
detector output.
"""
from __future__ import annotations

from datetime import datetime

import numpy as np

from app.anomaly_detection.rules import (
    SENSOR_FAULT_SEVERITY,
    blockage_severity,
    degradation_severity,
    leak_severity,
    tank_severity,
)
from app.simulation.engine import FaultEvent
from app.simulation.process_model import ProcessModel

SENSOR_MODES = ["FLATLINE", "SPIKE", "OUT_OF_RANGE", "MISSING", "BIAS"]


def _window(rng: np.random.Generator, n: int, lo_frac: float, hi_frac: float, min_len: int) -> tuple[int, int]:
    length = max(min_len, int(round(rng.uniform(lo_frac, hi_frac) * n)))
    length = min(length, max(min_len, n // 2))
    start = int(rng.integers(int(0.08 * n), max(int(0.08 * n) + 1, n - length - 2)))
    return start, start + length


def build_fault_schedule(models: list[ProcessModel], n_steps: int, rng: np.random.Generator) -> list[FaultEvent]:
    events: list[FaultEvent] = []
    mode_idx = 0
    for f_i, model in enumerate(models):
        lines = sorted(model.lines, key=lambda ln: ln.pump_id)
        order = rng.permutation(len(lines))
        leak_ln, blk_ln, deg_ln = (lines[int(i)] for i in order[:3])

        s, e = _window(rng, n_steps, 0.06, 0.10, 6)
        events.append(FaultEvent("PIPE_LEAK", leak_ln.last_pipe_id, s, e, round(float(rng.uniform(0.08, 0.20)), 3)))
        s, e = _window(rng, n_steps, 0.05, 0.08, 6)
        events.append(FaultEvent("PIPE_BLOCKAGE", blk_ln.last_pipe_id, s, e, round(float(rng.uniform(40, 65)), 1)))
        s, e = _window(rng, n_steps, 0.08, 0.14, 8)
        events.append(FaultEvent("PUMP_DEGRADATION", deg_ln.pump_id, s, e, round(float(rng.uniform(0.68, 0.85)), 3)))

        faulted = {leak_ln.pump_id, blk_ln.pump_id, deg_ln.pump_id}
        excluded = set()
        for ln in lines:
            if ln.pump_id in faulted:
                excluded |= set(ln.sensors.values())
                excluded.add(next((sid for sid, t in model.sensor_map.items()
                                   if t == ("TANK", ln.dst_tank_id, "level_pct")), ""))
                excluded.add(next((sid for sid, t in model.sensor_map.items()
                                   if t == ("TANK", ln.src_tank_id, "level_pct")), ""))
        candidates = sorted(sid for sid in model.sensor_map if sid not in excluded)
        bias_candidates = sorted(ln.sensors["flow_down"] for ln in lines
                                 if ln.pump_id not in faulted and "flow_down" in ln.sensors)
        used: set[str] = set()
        for _ in range(3):
            mode = SENSOR_MODES[mode_idx % len(SENSOR_MODES)]
            mode_idx += 1
            pool = [c for c in (bias_candidates if mode == "BIAS" else candidates) if c not in used]
            if not pool:
                continue
            sid = pool[int(rng.integers(0, len(pool)))]
            used.add(sid)
            # the bias meter's line is no longer "clean" for other sensor faults
            if mode == "BIAS":
                for ln in lines:
                    if ln.sensors.get("flow_down") == sid:
                        used |= set(ln.sensors.values())
            if mode == "SPIKE":
                s, e = _window(rng, n_steps, 0.02, 0.03, 6)
                events.append(FaultEvent("SENSOR_FAULT", sid, s, e, 3, mode))
            elif mode == "BIAS":
                s, e = _window(rng, n_steps, 0.05, 0.08, 8)
                events.append(FaultEvent("SENSOR_FAULT", sid, s, e, round(float(rng.uniform(0.10, 0.15)), 3), mode))
            else:
                s, e = _window(rng, n_steps, 0.02, 0.04, 10)
                events.append(FaultEvent("SENSOR_FAULT", sid, s, e, 0.0, mode))

        # Detection-limit tests (full scale only): magnitudes near or below the
        # documented thresholds, so evaluation reflects real detection limits.
        spare = [lines[int(i)] for i in order[3:] if lines[int(i)].pump_id not in faulted
                 and not (set(lines[int(i)].sensors.values()) & used)]
        if n_steps >= 300 and spare:
            ln = spare[0]
            s, e = _window(rng, n_steps, 0.06, 0.10, 8)
            if f_i == 0:
                events.append(FaultEvent("PIPE_LEAK", ln.last_pipe_id, s, e, 0.06, "SUBTLE"))
            elif f_i == 1:
                events.append(FaultEvent("PIPE_LEAK", ln.last_pipe_id, s, e, 0.035, "SUBTLE"))
            else:
                events.append(FaultEvent("PUMP_DEGRADATION", ln.pump_id, s, e, 0.93, "SUBTLE"))
            if len(spare) > 1 and f_i == 0 and "flow_down" in spare[1].sensors:
                s, e = _window(rng, n_steps, 0.05, 0.08, 8)
                events.append(FaultEvent("SENSOR_FAULT", spare[1].sensors["flow_down"], s, e, 0.04, "BIAS"))

        if f_i == 0 and model.outlets:
            # operator throttles one outlet valve -> end tank fills (overcapacity)
            ob = sorted(model.outlets, key=lambda b: b.valve_id)[int(rng.integers(0, len(model.outlets)))]
            s, e = _window(rng, n_steps, 0.10, 0.14, 12)
            events.append(FaultEvent("VALVE_POSITION", ob.valve_id, s, e, 15.0, "OPERATOR_THROTTLE"))

    for i, ev in enumerate(events, start=1):
        ev.event_id = f"INJ-{i:04d}"
    return events


def _expected_line_flow(model: ProcessModel, ln, h_src: np.ndarray, h_dst: np.ndarray) -> np.ndarray:
    pump = model.pumps[ln.pump_id]
    s = pump["speed_pct"] / 100
    r_suc, r_up, _ = model.line_resistances(ln)
    ts, td = model.tanks[ln.src_tank_id], model.tanks[ln.dst_tank_id]
    hs = (td["elevation_m"] + h_dst / 100 * td["height_m"]) - (ts["elevation_m"] + h_src / 100 * ts["height_m"])
    a = pump["health_factor"] * s * s * pump["shutoff_head_m"] - hs
    return np.where(a > 0, np.sqrt(np.clip(a, 0, None) / (pump["health_factor"] * pump["curve_k"] + r_suc + r_up)), 0)


def build_ground_truth(
    models: dict[str, ProcessModel],
    results: dict[str, dict],
    events: list[FaultEvent],
    timestamps: list[datetime],
    step_minutes: int,
) -> dict:
    labels = []
    operational_events = []
    n = len(timestamps)

    def ts_at(i: int) -> str:
        i = min(max(i, 0), n - 1)
        return timestamps[i].isoformat()

    for ev in events:
        fac = next(fid for fid, m in models.items()
                   if ev.target_id in m.pipes or ev.target_id in m.pumps or ev.target_id in m.sensors
                   or ev.target_id in m.valves)
        model = models[fac]
        base = {"injection_id": ev.event_id, "facility_id": fac, "equipment_id": ev.target_id,
                "start_timestamp": ts_at(ev.start_step), "end_timestamp": ts_at(ev.end_step - 1),
                "start_step": ev.start_step, "end_step": ev.end_step - 1, "magnitude": ev.magnitude,
                "detection_limit_test": ev.mode == "SUBTLE" or (ev.mode == "BIAS" and ev.magnitude < 0.05)}
        if ev.kind == "PIPE_LEAK":
            labels.append({**base, "equipment_type": "PIPE", "issue_type": "LEAK", "sub_type": "PIPE_LEAK",
                           "expected_detection": True, "expected_severity": leak_severity(ev.magnitude),
                           "injection_rule": f"Leak of {ev.magnitude * 100:.1f}% of line flow on transfer main"})
        elif ev.kind == "PIPE_BLOCKAGE":
            ln = model.line_for_pipe(ev.target_id)
            res = results[fac]
            lv = res["tanks"]
            q_true = res["lines"][ln.pump_id]["q_down"][ev.start_step:ev.end_step]
            q_exp = _expected_line_flow(model, ln, lv[ln.src_tank_id]["level_pct"][ev.start_step:ev.end_step],
                                        lv[ln.dst_tank_id]["level_pct"][ev.start_step:ev.end_step])
            red = float(1 - q_true.mean() / q_exp.mean()) if q_exp.mean() > 0 else 0.0
            labels.append({**base, "equipment_type": "PIPE", "issue_type": "BLOCKAGE", "sub_type": "PIPE_RESTRICTION",
                           "expected_detection": True, "expected_severity": blockage_severity(red),
                           "true_flow_reduction_pct": round(red * 100, 2),
                           "injection_rule": f"{ev.magnitude:.0f}% flow-area restriction on transfer main"})
        elif ev.kind == "PUMP_DEGRADATION":
            labels.append({**base, "equipment_type": "PUMP", "issue_type": "PUMP_DEGRADATION",
                           "sub_type": "HEAD_LOSS", "expected_detection": True,
                           "expected_severity": degradation_severity(1 - ev.magnitude),
                           "injection_rule": f"Pump health factor {ev.magnitude:.2f} "
                                             f"({(1 - ev.magnitude) * 100:.0f}% head loss)"})
        elif ev.kind == "SENSOR_FAULT":
            labels.append({**base, "equipment_type": "SENSOR", "issue_type": "SENSOR_FAULT", "sub_type": ev.mode,
                           "expected_detection": True, "expected_severity": SENSOR_FAULT_SEVERITY[ev.mode],
                           "injection_rule": f"Sensor fault mode {ev.mode}"})
        else:
            operational_events.append({**base, "kind": ev.kind, "mode": ev.mode, "expected_detection": False,
                                       "note": "Operator action (not a fault); consequences labelled separately."})

    # Tank overcapacity from the TRUE level (documented rule: true level >= 95 %)
    for fac, res in results.items():
        for tid, t in models[fac].tanks.items():
            lvl = res["tanks"][tid]["level_pct"]
            mask = lvl >= t["high_alarm_pct"]
            i = 0
            while i < n:
                if mask[i]:
                    j = i
                    while j + 1 < n and mask[j + 1]:
                        j += 1
                    if j - i + 1 >= 2:
                        peak = float(lvl[i:j + 1].max())
                        overflow = float(res["tanks"][tid]["overflow_m3"][i:j + 1].sum())
                        labels.append({
                            "injection_id": None, "facility_id": fac, "equipment_id": tid, "equipment_type": "TANK",
                            "issue_type": "TANK_OVERCAPACITY", "sub_type": "HIGH_LEVEL",
                            "start_timestamp": ts_at(i), "end_timestamp": ts_at(j), "start_step": i, "end_step": j,
                            "magnitude": round(peak, 2), "expected_detection": True,
                            "expected_severity": tank_severity(peak if overflow <= 0 else 100.0),
                            "overflow_m3": round(overflow, 2),
                            "injection_rule": "True tank level >= high alarm (95 %) for >= 2 samples",
                        })
                    i = j + 1
                else:
                    i += 1

    labels.sort(key=lambda r: (r["start_step"], r["facility_id"], r["equipment_id"]))
    for i, lab in enumerate(labels, start=1):
        lab["scenario_id"] = f"GT-{i:04d}"
    return {"labels": labels, "operational_events": operational_events, "step_minutes": step_minutes,
            "start": timestamps[0].isoformat(), "end": timestamps[-1].isoformat(), "n_steps": n}
