"""Rule-based, explainable anomaly detection over (simulated) telemetry.

Inputs: a ProcessModel holding the *known* plant configuration (what operators
and the control system know: speeds, valve positions, pump curves), plus sensor
readings. Injected faults and ground-truth labels are never passed in.

Pipeline:
1. Sensor validation  -> SENSOR_FAULT events + validity mask per reading.
2. Process rules on validated data (pump lines, tanks, boundaries).
3. Flow reconciliation separates real leaks from flow-meter faults using tank
   level changes (three-way balance).
4. Contiguous flagged samples are merged into events with persistence.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime

import numpy as np
import pandas as pd

from app.anomaly_detection.rules import (
    RECOMMENDED_ACTIONS,
    RULE_DESCRIPTIONS,
    SENSOR_FAULT_SEVERITY,
    THRESHOLDS,
    Thresholds,
    blockage_severity,
    degradation_severity,
    leak_severity,
    tank_severity,
)
from app.config import RHO_G_BAR_PER_M
from app.services.mass_balance import _fill, facility_balance
from app.simulation.engine import OperatingSettings
from app.simulation.process_model import ProcessModel, PumpLine, tank_level_sensor


@dataclass
class DetectionResult:
    anomalies: list[dict]
    invalid: dict[str, np.ndarray]  # sensor id -> bool mask of invalid readings
    sensor_fault_sensors: set[str]
    mass_balance: list[dict]


def runs(mask: np.ndarray, min_len: int = 1, max_gap: int = 1) -> list[tuple[int, int]]:
    """Contiguous True runs (inclusive start, inclusive end), bridging gaps of
    up to ``max_gap`` False samples, keeping runs with >= min_len True samples."""
    idx = np.flatnonzero(mask)
    if idx.size == 0:
        return []
    out = []
    s = prev = idx[0]
    count = 1
    for i in idx[1:]:
        if i - prev <= max_gap + 1:
            prev = i
            count += 1
            continue
        if count >= min_len:
            out.append((int(s), int(prev)))
        s = prev = i
        count = 1
    if count >= min_len:
        out.append((int(s), int(prev)))
    return out


def _fingerprint(*parts) -> str:
    return hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()[:40]


class Detector:
    def __init__(self, model: ProcessModel, settings: OperatingSettings | None = None,
                 thresholds: Thresholds = THRESHOLDS):
        self.m = model
        self.settings = settings or OperatingSettings()
        self.th = thresholds

    # ------------------------------------------------------------------ utils
    def _event(self, ts: list[datetime], s: int, e: int, persistence: int, **kw) -> dict:
        det_idx = min(s + max(persistence, 1) - 1, len(ts) - 1)
        a_type = kw["anomaly_type"]
        rule = kw["detection_rule"]
        ev = {
            "facility_id": self.m.facility_id,
            "sensor_id": None,
            "category": "PROCESS",
            "unit": "",
            "evidence": {},
            "recommended_action": RECOMMENDED_ACTIONS.get(a_type, ""),
            "rule_description": RULE_DESCRIPTIONS.get(rule, ""),
            "start_time": ts[s],
            "end_time": ts[e],
            "detected_at": ts[det_idx],
            "start_index": s,
            "end_index": e,
        }
        ev.update(kw)
        for k in ("observed_value", "expected_value", "threshold"):
            if ev.get(k) is not None:
                ev[k] = float(round(ev[k], 4))
        ev["fingerprint"] = _fingerprint(ev["facility_id"], ev["equipment_id"], ev.get("sensor_id"), a_type,
                                         rule, ts[s].isoformat())
        return ev

    def _speed(self, pump_id: str) -> float:
        p = self.m.pumps[pump_id]
        return self.settings.pump_speed_pct.get(pump_id, p["speed_pct"]) / 100.0

    def _available(self, pump_id: str) -> bool:
        p = self.m.pumps[pump_id]
        return bool(self.settings.pump_available.get(pump_id, p["available"]))

    # ------------------------------------------------------- 1. sensor checks
    def validate_sensors(self, readings: dict[str, np.ndarray], ts: list[datetime]):
        th = self.th
        invalid: dict[str, np.ndarray] = {}
        events: list[dict] = []
        for sid, raw in readings.items():
            s = self.m.sensors.get(sid)
            if s is None:
                continue
            v = np.asarray(raw, dtype=float)
            lo, hi = s["min_range"], s["max_range"]
            span = hi - lo
            missing = np.isnan(v)
            with np.errstate(invalid="ignore"):
                oor = (~missing) & ((v < lo - 1e-3 * span) | (v > hi + 1e-3 * span))
            # flatline: identical consecutive values, not at range limits
            flat = np.zeros(v.size, dtype=bool)
            same = np.zeros(v.size, dtype=bool)
            same[1:] = (v[1:] == v[:-1]) & ~missing[1:]
            interior = (~missing) & (v > lo + 0.01 * span) & (v < hi - 0.01 * span)
            run_start = 0
            for i in range(1, v.size + 1):
                if i == v.size or not same[i]:
                    length = i - run_start
                    if length >= th.flatline_steps and interior[run_start:i].all():
                        flat[run_start:i] = True
                    run_start = i
            # spike: deviation from centred rolling median
            ser = pd.Series(np.where(oor, np.nan, v))
            med = ser.rolling(5, center=True, min_periods=3).median().to_numpy()
            with np.errstate(invalid="ignore"):
                spike = (~missing) & (~oor) & (np.abs(v - med) > th.spike_fraction_of_span * span)
            invalid[sid] = missing | oor | flat | spike
            eq_type, eq_id = s["equipment_type"], s["equipment_id"]
            checks = (
                ("MISSING", "SENSOR_MISSING", missing, th.missing_persistence, 0),
                ("OUT_OF_RANGE", "SENSOR_OUT_OF_RANGE", oor, 1, 1),
                ("FLATLINE", "SENSOR_FLATLINE", flat, th.flatline_steps, 0),
                ("SPIKE", "SENSOR_SPIKE", spike, 1, 2),
            )
            for mode, rule, mask, persist, gap in checks:
                min_len = persist if mode != "FLATLINE" else 1
                for a, b in runs(mask, min_len=min_len, max_gap=gap):
                    seg = v[a:b + 1]
                    observed = None if mode == "MISSING" else float(np.nanmean(seg)) if not np.isnan(seg).all() else None
                    if mode == "SPIKE":
                        dev = np.abs(seg - med[a:b + 1])
                        observed = float(seg[int(np.nanargmax(dev))])
                    expected = float(np.nanmedian(med[a:b + 1])) if mode in ("SPIKE",) else None
                    threshold = {"OUT_OF_RANGE": hi, "SPIKE": th.spike_fraction_of_span * span,
                                 "FLATLINE": float(th.flatline_steps), "MISSING": float(th.missing_persistence)}[mode]
                    events.append(self._event(
                        ts, a, b, persist if mode != "FLATLINE" else th.flatline_steps,
                        equipment_type=eq_type, equipment_id=eq_id, sensor_id=sid, anomaly_type="SENSOR_FAULT",
                        category="SENSOR", severity=SENSOR_FAULT_SEVERITY[mode], detection_rule=rule,
                        observed_value=observed, expected_value=expected, threshold=threshold, unit=s["unit"],
                        evidence={"fault_mode": mode, "samples": int(b - a + 1), "sensor_tag": s["tag"],
                                  "range": [lo, hi]},
                    ))
        return invalid, events

    # ----------------------------------------------------- 2. process rules
    def _clean(self, readings, invalid, sid):
        if sid is None or sid not in readings:
            return None
        v = np.asarray(readings[sid], dtype=float).copy()
        v[invalid.get(sid, np.zeros(v.size, bool))] = np.nan
        return v

    def _tank_flows(self, tank_id, readings, invalid, exclude_line: PumpLine | None):
        """Measured inflow and outflow (m3/h, NaN-filled) of a tank excluding one line."""
        n = len(next(iter(readings.values())))
        q_in = np.zeros(n)
        q_out = np.zeros(n)
        for ln in self.m.lines:
            if exclude_line is not None and ln.pump_id == exclude_line.pump_id:
                continue
            if ln.dst_tank_id == tank_id:
                sid = ln.sensors.get("flow_down") or ln.sensors.get("flow_up")
                v = self._clean(readings, invalid, sid)
                if v is not None:
                    q_in += _fill(v)
            if ln.src_tank_id == tank_id:
                v = self._clean(readings, invalid, ln.sensors.get("flow_up"))
                if v is not None:
                    q_out += _fill(v)
        for b in self.m.inlets:
            if b.tank_id == tank_id:
                v = self._clean(readings, invalid, b.sensors.get("flow"))
                if v is not None:
                    q_in += _fill(v)
        for b in self.m.outlets:
            if b.tank_id == tank_id:
                v = self._clean(readings, invalid, b.sensors.get("flow"))
                if v is not None:
                    q_out += _fill(v)
        return q_in, q_out

    def _tank_residuals(self, tank_id, s, e, readings, invalid, line, line_flow_a, line_flow_b, direction, dt_h):
        """Residual |dV_measured - integral(net flow)| over [s, e] for two hypotheses
        of the line flow (a / b). direction='in' when the line feeds the tank."""
        lsid = tank_level_sensor(self.m, tank_id)
        lv = self._clean(readings, invalid, lsid)
        if lv is None:
            return None
        n = lv.size
        e2 = min(e + 1, n - 1)
        if np.isnan(lv[s]) or np.isnan(lv[e2]) or e2 <= s:
            seg = lv[s:e2 + 1]
            if np.isnan(seg).sum() > seg.size / 2:
                return None
            lv = _fill(lv)
        cap = self.m.tanks[tank_id]["capacity_m3"]
        dv = (lv[e2] - lv[s]) / 100.0 * cap
        q_in, q_out = self._tank_flows(tank_id, readings, invalid, line)
        base = float((q_in[s:e2] - q_out[s:e2]).sum() * dt_h)
        sign = 1.0 if direction == "in" else -1.0
        ra = abs(dv - (base + sign * float(line_flow_a[s:e2].sum()) * dt_h))
        rb = abs(dv - (base + sign * float(line_flow_b[s:e2].sum()) * dt_h))
        return ra, rb, dv

    def line_rules(self, ln: PumpLine, readings, invalid, ts, dt_h, sensor_fault_sensors: set[str]) -> list[dict]:
        th = self.th
        events: list[dict] = []
        pump = self.m.pumps[ln.pump_id]
        rated = pump["rated_flow_m3h"]
        s = self._speed(ln.pump_id)
        running = self._available(ln.pump_id) and s > 0
        hf = pump["health_factor"]
        H0, k = pump["shutoff_head_m"], pump["curve_k"]
        q_up = self._clean(readings, invalid, ln.sensors.get("flow_up"))
        q_dn = self._clean(readings, invalid, ln.sensors.get("flow_down"))
        p_s = self._clean(readings, invalid, ln.sensors.get("p_suction"))
        p_d = self._clean(readings, invalid, ln.sensors.get("p_discharge"))
        l_src = self._clean(readings, invalid, tank_level_sensor(self.m, ln.src_tank_id))
        l_dst = self._clean(readings, invalid, tank_level_sensor(self.m, ln.dst_tank_id))
        n = len(ts)
        nan = np.full(n, np.nan)
        q_up = nan if q_up is None else q_up
        q_dn = nan if q_dn is None else q_dn
        p_s = nan if p_s is None else p_s
        p_d = nan if p_d is None else p_d

        valve_open = dict(self.settings.valve_opening_pct)
        r_suc, r_up, _ = self.m.line_resistances(ln, None, valve_open, None)
        r_tot = r_suc + r_up
        valve_closed = np.isinf(r_tot)

        # model-expected flow from measured tank levels (nominal pump, known config)
        if l_src is not None and l_dst is not None:
            ts_src, ts_dst = self.m.tanks[ln.src_tank_id], self.m.tanks[ln.dst_tank_id]
            hs = (ts_dst["elevation_m"] + l_dst / 100 * ts_dst["height_m"]) - \
                 (ts_src["elevation_m"] + l_src / 100 * ts_src["height_m"])
            if running and not valve_closed:
                a = hf * s * s * H0 - hs
                with np.errstate(invalid="ignore"):
                    q_exp = np.where(a > 0, np.sqrt(np.clip(a, 0, None) / (hf * k + r_tot)), 0.0)
            else:
                q_exp = np.zeros(n)
        else:
            q_exp = nan

        with np.errstate(invalid="ignore", divide="ignore"):
            h_obs = (p_d - p_s) / RHO_G_BAR_PER_M
            h_curve_obs = hf * (s * s * H0 - k * q_up**2)
            h_curve_exp = hf * (s * s * H0 - k * q_exp**2)
            p_d_exp = p_s + h_curve_exp * RHO_G_BAR_PER_M
            min_flow = th.min_flow_fraction_of_rated * rated

            # --- leak / flow reconciliation --------------------------------
            imb = np.where(q_up > min_flow, (q_up - q_dn) / q_up, np.nan)
            imb_mask = np.abs(imb) > th.leak_imbalance_fraction
        for a_, b_ in runs(np.nan_to_num(imb_mask, nan=0).astype(bool), th.persistence_steps, 1):
            mean_imb = float(np.nanmean(imb[a_:b_ + 1]))
            qa, qb = _fill(q_up), _fill(q_dn)
            dst_res = self._tank_residuals(ln.dst_tank_id, a_, b_, readings, invalid, ln, qa, qb, "in", dt_h)
            src_res = self._tank_residuals(ln.src_tank_id, a_, b_, readings, invalid, ln, qa, qb, "out", dt_h)
            evidence = {
                "mean_upstream_flow_m3h": round(float(np.nanmean(q_up[a_:b_ + 1])), 3),
                "mean_downstream_flow_m3h": round(float(np.nanmean(q_dn[a_:b_ + 1])), 3),
                "mean_imbalance_pct": round(mean_imb * 100, 2),
                "upstream_sensor": ln.sensors.get("flow_up"), "downstream_sensor": ln.sensors.get("flow_down"),
                "pump_id": ln.pump_id,
            }
            faulty_sid = None
            if dst_res is not None:
                evidence["dst_tank_residual_if_upstream_meter_true_m3"] = round(dst_res[0], 2)
                evidence["dst_tank_residual_if_downstream_meter_true_m3"] = round(dst_res[1], 2)
            if src_res is not None:
                evidence["src_tank_residual_if_upstream_meter_true_m3"] = round(src_res[0], 2)
                evidence["src_tank_residual_if_downstream_meter_true_m3"] = round(src_res[1], 2)
            if mean_imb > 0:
                # Q_up > Q_down: either a real loss (leak) or a meter error
                if dst_res is not None and dst_res[0] < dst_res[1]:
                    faulty_sid = ln.sensors.get("flow_down")  # tank confirms the upstream flow arrived
                elif src_res is not None and src_res[1] < src_res[0]:
                    faulty_sid = ln.sensors.get("flow_up")  # source tank confirms the lower flow left
            else:
                # Q_down > Q_up is physically impossible without another inflow
                if dst_res is not None and dst_res[0] < dst_res[1]:
                    faulty_sid = ln.sensors.get("flow_down")
                else:
                    faulty_sid = ln.sensors.get("flow_up")
            if faulty_sid:
                evidence["classification"] = "Flow meter inconsistent with tank level change -> SENSOR fault"
                sensor_fault_sensors.add(faulty_sid)
                sen = self.m.sensors[faulty_sid]
                events.append(self._event(
                    ts, a_, b_, th.persistence_steps, equipment_type=sen["equipment_type"],
                    equipment_id=sen["equipment_id"], sensor_id=faulty_sid, anomaly_type="SENSOR_FAULT",
                    category="SENSOR", severity=SENSOR_FAULT_SEVERITY["INCONSISTENT"],
                    detection_rule="FLOW_RECONCILIATION", observed_value=abs(mean_imb) * 100, expected_value=0.0,
                    threshold=th.leak_imbalance_fraction * 100, unit="%", evidence={**evidence, "fault_mode": "INCONSISTENT"},
                ))
            else:
                evidence["classification"] = ("Downstream tank level confirms the lower delivered flow -> process loss"
                                              if dst_res is not None else "Tank reconciliation unavailable")
                events.append(self._event(
                    ts, a_, b_, th.persistence_steps, equipment_type="PIPE", equipment_id=ln.last_pipe_id,
                    anomaly_type="LEAK", category="PROCESS", severity=leak_severity(mean_imb),
                    detection_rule="LEAK_FLOW_IMBALANCE", observed_value=mean_imb * 100, expected_value=0.0,
                    threshold=th.leak_imbalance_fraction * 100, unit="%", evidence=evidence,
                ))

        leak_like = np.nan_to_num(imb_mask, nan=0).astype(bool)

        if running:
            with np.errstate(invalid="ignore", divide="ignore"):
                # --- blockage ------------------------------------------------
                q_obs = np.where(np.isnan(q_dn), q_up, q_dn)
                blk = (q_exp > 2 * min_flow) & (q_obs < th.blockage_flow_fraction * q_exp) & \
                      ((p_d - p_d_exp) > th.blockage_pressure_rise_bar) & ~leak_like
            for a_, b_ in runs(np.nan_to_num(blk, nan=0).astype(bool), th.persistence_steps, 1):
                qo = float(np.nanmean(q_obs[a_:b_ + 1]))
                qe = float(np.nanmean(q_exp[a_:b_ + 1]))
                red = 1 - qo / qe if qe > 0 else 0
                block_pipe = max(ln.discharge_pipe_ids,
                                 key=lambda p: self.m.pipes[p]["length_m"]) if ln.discharge_pipe_ids else ln.last_pipe_id
                events.append(self._event(
                    ts, a_, b_, th.persistence_steps, equipment_type="PIPE", equipment_id=block_pipe,
                    anomaly_type="BLOCKAGE", category="PROCESS", severity=blockage_severity(red),
                    detection_rule="BLOCKAGE_FLOW_PRESSURE", observed_value=qo, expected_value=qe,
                    threshold=th.blockage_flow_fraction * qe, unit="m3/h",
                    evidence={"pump_id": ln.pump_id, "flow_reduction_pct": round(red * 100, 2),
                              "mean_discharge_pressure_bar": round(float(np.nanmean(p_d[a_:b_ + 1])), 3),
                              "expected_discharge_pressure_bar": round(float(np.nanmean(p_d_exp[a_:b_ + 1])), 3),
                              "line_pipes": ln.discharge_pipe_ids},
                ))

            with np.errstate(invalid="ignore", divide="ignore"):
                # --- pump degradation ---------------------------------------
                ratio = np.where((q_up > 2 * min_flow) & (h_curve_obs > 1.0), h_obs / h_curve_obs, np.nan)
                deg = ratio < th.degradation_head_ratio
                # A pump drawing from a (nearly) empty tank loses head through cavitation /
                # dry running; that is a supply problem (reported as TANK_LOW_LEVEL), not wear.
                if l_src is not None:
                    low_suction = l_src <= self.m.tanks[ln.src_tank_id]["low_alarm_pct"]
                    deg = deg & ~np.nan_to_num(low_suction, nan=0).astype(bool)
            for a_, b_ in runs(np.nan_to_num(deg, nan=0).astype(bool), th.persistence_steps, 1):
                ho = float(np.nanmean(h_obs[a_:b_ + 1]))
                he = float(np.nanmean(h_curve_obs[a_:b_ + 1]))
                deficit = 1 - ho / he if he > 0 else 0
                events.append(self._event(
                    ts, a_, b_, th.persistence_steps, equipment_type="PUMP", equipment_id=ln.pump_id,
                    anomaly_type="PUMP_DEGRADATION", category="PROCESS", severity=degradation_severity(deficit),
                    detection_rule="PUMP_HEAD_DEFICIT", observed_value=ho, expected_value=he,
                    threshold=th.degradation_head_ratio * he, unit="m",
                    evidence={"head_deficit_pct": round(deficit * 100, 2),
                              "performance_index": round(1 - deficit, 3),
                              "mean_flow_m3h": round(float(np.nanmean(q_up[a_:b_ + 1])), 2),
                              "speed_pct": round(s * 100, 1)},
                ))

            with np.errstate(invalid="ignore"):
                # --- deadhead / no delivery ------------------------------------
                no_flow = q_up < th.deadhead_flow_fraction * rated
                shutoff = hf * s * s * H0
                dead = no_flow & (h_obs > 0.8 * shutoff)
                nodel = no_flow & (h_obs < 0.2 * shutoff) & (q_exp > 2 * min_flow)
            if valve_closed:
                for a_, b_ in runs(np.nan_to_num(dead, nan=0).astype(bool), th.persistence_steps, 1):
                    events.append(self._event(
                        ts, a_, b_, th.persistence_steps, equipment_type="PUMP", equipment_id=ln.pump_id,
                        anomaly_type="ABNORMAL_FLOW", category="OPERATIONAL", severity="HIGH",
                        detection_rule="PUMP_DEADHEAD", observed_value=float(np.nanmean(q_up[a_:b_ + 1])),
                        expected_value=0.0, threshold=th.deadhead_flow_fraction * rated, unit="m3/h",
                        evidence={"closed_valves": [v for v in ln.valve_ids if np.isinf(
                            self.m.element_resistance("VALVE", v, None, valve_open))],
                            "head_m": round(float(np.nanmean(h_obs[a_:b_ + 1])), 2)},
                        recommended_action="Pump is running against a closed valve: stop the pump or open the valve "
                                           "to avoid overheating and seal damage.",
                    ))
            for a_, b_ in runs(np.nan_to_num(nodel, nan=0).astype(bool), th.persistence_steps, 1):
                events.append(self._event(
                    ts, a_, b_, th.persistence_steps, equipment_type="PUMP", equipment_id=ln.pump_id,
                    anomaly_type="ABNORMAL_FLOW", category="OPERATIONAL", severity="HIGH",
                    detection_rule="PUMP_NO_DELIVERY", observed_value=float(np.nanmean(q_up[a_:b_ + 1])),
                    expected_value=float(np.nanmean(q_exp[a_:b_ + 1])), threshold=th.deadhead_flow_fraction * rated,
                    unit="m3/h", evidence={"suction_tank": ln.src_tank_id},
                    recommended_action="Pump commanded on but not delivering: check for trip, dry running "
                                       "(low suction tank level) or loss of prime.",
                ))

            with np.errstate(invalid="ignore"):
                low_suc = p_s < th.low_suction_bar
            for a_, b_ in runs(np.nan_to_num(low_suc, nan=0).astype(bool), th.persistence_steps, 1):
                events.append(self._event(
                    ts, a_, b_, th.persistence_steps, equipment_type="PUMP", equipment_id=ln.pump_id,
                    anomaly_type="ABNORMAL_PRESSURE", category="PROCESS", severity="MEDIUM",
                    detection_rule="LOW_SUCTION_PRESSURE", observed_value=float(np.nanmin(p_s[a_:b_ + 1])),
                    expected_value=None, threshold=th.low_suction_bar, unit="bar",
                    evidence={"suction_tank": ln.src_tank_id},
                ))

        # --- over-pressure & over-capacity (independent of run state) ----------
        dis_pipes = ln.discharge_pipe_ids
        if dis_pipes:
            p_max = min(self.m.pipes[p]["max_pressure_bar"] for p in dis_pipes)
            with np.errstate(invalid="ignore"):
                over = p_d >= th.pressure_warning_fraction * p_max
            for a_, b_ in runs(np.nan_to_num(over, nan=0).astype(bool), 2, 1):
                peak = float(np.nanmax(p_d[a_:b_ + 1]))
                events.append(self._event(
                    ts, a_, b_, 2, equipment_type="PIPE", equipment_id=dis_pipes[0], anomaly_type="ABNORMAL_PRESSURE",
                    category="PROCESS", severity="CRITICAL" if peak >= p_max else "HIGH",
                    detection_rule="PIPE_OVERPRESSURE", observed_value=peak, expected_value=None,
                    threshold=th.pressure_warning_fraction * p_max, unit="bar",
                    evidence={"pipe_rating_bar": p_max, "pump_id": ln.pump_id},
                ))
            q_max = min(self.m.pipes[p]["max_flow_m3h"] for p in ln.pipe_ids)
            with np.errstate(invalid="ignore"):
                hiq = q_up > q_max
            for a_, b_ in runs(np.nan_to_num(hiq, nan=0).astype(bool), th.persistence_steps, 1):
                events.append(self._event(
                    ts, a_, b_, th.persistence_steps, equipment_type="PUMP", equipment_id=ln.pump_id,
                    anomaly_type="ABNORMAL_FLOW", category="PROCESS", severity="HIGH",
                    detection_rule="FLOW_ABOVE_CAPACITY", observed_value=float(np.nanmax(q_up[a_:b_ + 1])),
                    expected_value=None, threshold=q_max, unit="m3/h", evidence={"line_pipes": ln.pipe_ids},
                ))
        return events

    def boundary_rules(self, readings, invalid, ts) -> list[dict]:
        events = []
        for b in self.m.outlets + self.m.inlets:
            sid = b.sensors.get("flow")
            v = self._clean(readings, invalid, sid)
            if v is None or not b.pipe_ids:
                continue
            q_max = min(self.m.pipes[p]["max_flow_m3h"] for p in b.pipe_ids)
            with np.errstate(invalid="ignore"):
                hiq = v > q_max
            for a_, b_ in runs(np.nan_to_num(hiq, nan=0).astype(bool), self.th.persistence_steps, 1):
                events.append(self._event(
                    ts, a_, b_, self.th.persistence_steps, equipment_type="VALVE", equipment_id=b.valve_id,
                    sensor_id=sid, anomaly_type="ABNORMAL_FLOW", category="PROCESS", severity="HIGH",
                    detection_rule="FLOW_ABOVE_CAPACITY", observed_value=float(np.nanmax(v[a_:b_ + 1])),
                    expected_value=None, threshold=q_max, unit="m3/h", evidence={"boundary": b.kind},
                ))
        return events

    def tank_rules(self, readings, invalid, ts) -> list[dict]:
        th = self.th
        events = []
        for tid, t in self.m.tanks.items():
            lv = self._clean(readings, invalid, tank_level_sensor(self.m, tid))
            if lv is None:
                continue
            with np.errstate(invalid="ignore"):
                high = lv >= t["high_alarm_pct"]
                low = lv <= t["low_alarm_pct"]
            for a_, b_ in runs(np.nan_to_num(high, nan=0).astype(bool), th.tank_high_persistence, 1):
                peak = float(np.nanmax(lv[a_:b_ + 1]))
                events.append(self._event(
                    ts, a_, b_, th.tank_high_persistence, equipment_type="TANK", equipment_id=tid,
                    anomaly_type="TANK_OVERCAPACITY", category="PROCESS", severity=tank_severity(peak),
                    detection_rule="TANK_HIGH_LEVEL", observed_value=peak, expected_value=t["setpoint_pct"],
                    threshold=t["high_alarm_pct"], unit="%",
                    evidence={"capacity_m3": t["capacity_m3"], "peak_volume_m3": round(peak / 100 * t["capacity_m3"], 1),
                              "overflow_likely": peak >= 99.5},
                ))
            for a_, b_ in runs(np.nan_to_num(low, nan=0).astype(bool), th.tank_high_persistence, 1):
                events.append(self._event(
                    ts, a_, b_, th.tank_high_persistence, equipment_type="TANK", equipment_id=tid,
                    anomaly_type="ABNORMAL_LEVEL", category="PROCESS", severity="MEDIUM",
                    detection_rule="TANK_LOW_LEVEL", observed_value=float(np.nanmin(lv[a_:b_ + 1])),
                    expected_value=t["setpoint_pct"], threshold=t["low_alarm_pct"], unit="%",
                    evidence={"capacity_m3": t["capacity_m3"]},
                ))
        return events

    # ---------------------------------------------------------------- main
    def detect(self, readings: dict[str, np.ndarray], timestamps: list[datetime], step_minutes: int,
               balance_window_steps: int | None = None, tolerance_pct: float | None = None) -> DetectionResult:
        dt_h = step_minutes / 60.0
        invalid, events = self.validate_sensors(readings, timestamps)
        sensor_fault_sensors = {e["sensor_id"] for e in events}
        for ln in self.m.lines:
            events += self.line_rules(ln, readings, invalid, timestamps, dt_h, sensor_fault_sensors)
        events += self.tank_rules(readings, invalid, timestamps)
        events += self.boundary_rules(readings, invalid, timestamps)

        # facility mass balance per window
        n = len(timestamps)
        win = balance_window_steps or n
        balances = []
        kwargs = {} if tolerance_pct is None else {"tolerance_pct": tolerance_pct}
        for s in range(0, n, win):
            e = min(s + win, n)
            if e - s < max(4, win // 4):
                continue
            mb = facility_balance(self.m, readings, step_minutes, s, e, invalid=invalid,
                                  sensor_fault_sensors=sensor_fault_sensors, **kwargs)
            mb["start_time"] = timestamps[s].isoformat()
            mb["end_time"] = timestamps[e - 1].isoformat()
            balances.append(mb)
            if mb["status"] == "EXCEPTION":
                cat = "SENSOR" if mb["classification"] == "MEASUREMENT_FAULT" else "PROCESS"
                events.append(self._event(
                    timestamps, s, e - 1, e - s, equipment_type="FACILITY", equipment_id=self.m.facility_id,
                    anomaly_type="MASS_BALANCE", category=cat,
                    severity="HIGH" if (mb["balance_error_pct"] or 0) > 3 * mb["tolerance_pct"] else "MEDIUM",
                    detection_rule="FACILITY_MASS_BALANCE", observed_value=mb["balance_error_pct"],
                    expected_value=0.0, threshold=mb["tolerance_pct"], unit="%",
                    evidence={k: mb[k] for k in ("total_inflow_m3", "total_outflow_m3", "storage_change_m3",
                                                 "residual_m3", "classification", "suspect_sensors")},
                    recommended_action=("Balance residual coincides with suspect instruments: verify meters before "
                                        "treating as physical loss." if cat == "SENSOR"
                                        else "Unexplained loss: inspect for leaks/overflows; see line_losses."),
                ))
        events.sort(key=lambda e: (e["start_time"], e["equipment_id"], e["anomaly_type"]))
        return DetectionResult(events, invalid, sensor_fault_sensors, balances)
