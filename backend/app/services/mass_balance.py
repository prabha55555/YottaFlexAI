"""Approximate mass (volume) balance engine.

Water is treated as incompressible, so a volume balance is equivalent to a mass
balance (m = rho * V, rho = 1000 kg/m3).

    balance residual = total inflow - total outflow - change in stored volume
    balance error %  = |residual| / total inflow * 100

Status: BALANCED (<= tol), WARNING (<= 2*tol), EXCEPTION (> 2*tol).
A residual is classified as MEASUREMENT_FAULT (instead of PROCESS_IMBALANCE)
when any instrument on the balance boundary is invalid in the window or the
flow-reconciliation rule attributed an imbalance to a faulty meter.
"""
from __future__ import annotations

import numpy as np

from app.config import MASS_BALANCE_TOLERANCE_PCT, MASS_BALANCE_WARNING_FACTOR
from app.simulation.process_model import ProcessModel, tank_level_sensor


def _fill(a: np.ndarray) -> np.ndarray:
    """Linear interpolation over NaN gaps (edge NaNs take nearest value)."""
    a = np.asarray(a, dtype=float)
    if a.size == 0:
        return a
    mask = np.isnan(a)
    if mask.all():
        return np.zeros_like(a)
    if mask.any():
        idx = np.arange(a.size)
        a = a.copy()
        a[mask] = np.interp(idx[mask], idx[~mask], a[~mask])
    return a


def _edge_mean(a: np.ndarray, at_start: bool, n: int = 3) -> float:
    seg = a[:n] if at_start else a[-n:]
    seg = seg[~np.isnan(seg)]
    return float(seg.mean()) if seg.size else float("nan")


def status_for(error_pct: float, tolerance_pct: float) -> str:
    if np.isnan(error_pct):
        return "INSUFFICIENT_DATA"
    if error_pct <= tolerance_pct:
        return "BALANCED"
    if error_pct <= tolerance_pct * MASS_BALANCE_WARNING_FACTOR:
        return "WARNING"
    return "EXCEPTION"


def facility_balance(
    model: ProcessModel,
    readings: dict[str, np.ndarray],
    step_minutes: int,
    start: int = 0,
    end: int | None = None,
    tolerance_pct: float = MASS_BALANCE_TOLERANCE_PCT,
    invalid: dict[str, np.ndarray] | None = None,
    sensor_fault_sensors: set[str] | None = None,
) -> dict:
    dt_h = step_minutes / 60.0
    n = len(next(iter(readings.values()))) if readings else 0
    end = n if end is None else min(end, n)
    sl = slice(start, end)
    invalid = invalid or {}
    sensor_fault_sensors = sensor_fault_sensors or set()

    def series(sid: str | None) -> np.ndarray | None:
        if sid is None or sid not in readings:
            return None
        v = readings[sid][sl].astype(float).copy()
        if sid in invalid:
            v[invalid[sid][sl]] = np.nan
        return v

    suspect: list[str] = []

    def note_suspect(sid: str | None) -> None:
        if sid is None:
            return
        bad = sid in sensor_fault_sensors or (sid in invalid and bool(invalid[sid][sl].any()))
        if bad:
            suspect.append(sid)

    inflow = 0.0
    inflow_detail = []
    for b in model.inlets:
        sid = b.sensors.get("flow")
        v = series(sid)
        note_suspect(sid)
        vol = float(np.nansum(_fill(v)) * dt_h) if v is not None else 0.0
        inflow += vol
        inflow_detail.append({"valve_id": b.valve_id, "sensor_id": sid, "volume_m3": round(vol, 2)})

    outflow = 0.0
    outflow_detail = []
    for b in model.outlets:
        sid = b.sensors.get("flow")
        v = series(sid)
        note_suspect(sid)
        vol = float(np.nansum(_fill(v)) * dt_h) if v is not None else 0.0
        outflow += vol
        outflow_detail.append({"valve_id": b.valve_id, "sensor_id": sid, "volume_m3": round(vol, 2)})

    storage_change = 0.0
    tank_detail = []
    for tid, t in model.tanks.items():
        sid = tank_level_sensor(model, tid)
        v = series(sid)
        note_suspect(sid)
        if v is None or np.isnan(v).all():
            continue
        # Volume at the boundary of the window: the flows integrated over steps
        # [start, end) move the tank from V(start) to V(end). Use the reading
        # at ``end`` when available, otherwise extrapolate with the last value.
        l0 = _edge_mean(v, True, 1)
        if end < n:
            nxt = readings[sid][end]
            l1 = float(nxt) if not np.isnan(nxt) else _edge_mean(v, False, 1)
        else:
            l1 = _edge_mean(v, False, 1)
        dv = (l1 - l0) / 100.0 * t["capacity_m3"]
        storage_change += dv
        tank_detail.append({"tank_id": tid, "sensor_id": sid, "start_level_pct": round(l0, 2),
                            "end_level_pct": round(l1, 2), "volume_change_m3": round(dv, 2)})

    residual = inflow - outflow - storage_change
    error_pct = abs(residual) / inflow * 100.0 if inflow > 1e-9 else float("nan")
    status = status_for(error_pct, tolerance_pct)

    # Internal pipe balances (pump discharge vs pipe end) localise losses
    line_losses = []
    for ln in model.lines:
        su, sd = ln.sensors.get("flow_up"), ln.sensors.get("flow_down")
        vu, vd = series(su), series(sd)
        if vu is None or vd is None:
            continue
        vol_up = float(np.nansum(_fill(vu)) * dt_h)
        vol_dn = float(np.nansum(_fill(vd)) * dt_h)
        loss = vol_up - vol_dn
        faulty = su in sensor_fault_sensors or sd in sensor_fault_sensors or \
            bool(su in invalid and invalid[su][sl].any()) or bool(sd in invalid and invalid[sd][sl].any())
        line_losses.append({
            "pump_id": ln.pump_id, "pipe_id": ln.last_pipe_id, "upstream_volume_m3": round(vol_up, 2),
            "downstream_volume_m3": round(vol_dn, 2), "loss_m3": round(loss, 2),
            "loss_pct": round(loss / vol_up * 100, 2) if vol_up > 1e-6 else None,
            "sensor_suspect": faulty,
        })

    if status in ("WARNING", "EXCEPTION"):
        classification = "MEASUREMENT_FAULT" if suspect else "PROCESS_IMBALANCE"
    elif status == "INSUFFICIENT_DATA":
        classification = "INSUFFICIENT_DATA"
    else:
        classification = "OK"

    estimated_leak = max(residual, 0.0) if classification != "MEASUREMENT_FAULT" else 0.0
    return {
        "facility_id": model.facility_id,
        "start_index": start,
        "end_index": end,
        "hours": round((end - start) * dt_h, 2),
        "tolerance_pct": tolerance_pct,
        "total_inflow_m3": round(inflow, 2),
        "total_outflow_m3": round(outflow, 2),
        "storage_change_m3": round(storage_change, 2),
        "residual_m3": round(residual, 2),
        "estimated_leakage_m3": round(estimated_leak, 2),
        "balance_error_pct": None if np.isnan(error_pct) else round(error_pct, 3),
        "status": status,
        "classification": classification,
        "suspect_sensors": sorted(set(suspect)),
        "inflows": inflow_detail,
        "outflows": outflow_detail,
        "tanks": tank_detail,
        "line_losses": line_losses,
    }


def true_balance(model: ProcessModel, result: dict) -> dict:
    """Closure check on the true simulated state (should be ~0 by construction)."""
    dt_h = result["step_minutes"] / 60.0
    inflow = sum(float(v["q"].sum()) for v in result["inlets"].values()) * dt_h
    outflow = sum(float(v["q"].sum()) for v in result["outlets"].values()) * dt_h
    leak = sum(float(v["leak"].sum()) for v in result["lines"].values()) * dt_h
    overflow = sum(float(v["overflow_m3"].sum()) for v in result["tanks"].values())
    v0 = sum(float(v["volume_m3"][0]) for v in result["tanks"].values())
    v1 = sum(result["final_volume"].values())
    closure = inflow - outflow - leak - overflow - (v1 - v0)
    return {
        "total_inflow_m3": round(inflow, 3),
        "total_outflow_m3": round(outflow, 3),
        "true_leak_m3": round(leak, 3),
        "overflow_m3": round(overflow, 3),
        "storage_change_m3": round(v1 - v0, 3),
        "closure_error_m3": round(closure, 6),
    }
