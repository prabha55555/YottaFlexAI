"""Convert true process states into simulated sensor readings.

Readings = true value + Gaussian measurement noise, clipped to the instrument
range (transmitters saturate at their range limits), quantised to 3 decimals.
Flow meters apply a low-flow cut-off (reading 0 below 0.5 % of span).
Sensor faults (flatline, spike, out-of-range, missing, bias) are applied on top.
"""
from __future__ import annotations

import numpy as np

from app.simulation.engine import FaultEvent, true_value
from app.simulation.process_model import ProcessModel

LOW_FLOW_CUTOFF_FRACTION = 0.005
SENSOR_FAULT_MODES = ("FLATLINE", "SPIKE", "OUT_OF_RANGE", "MISSING", "BIAS")


def noise_sigma(sensor: dict, values: np.ndarray) -> np.ndarray:
    span = sensor["max_range"] - sensor["min_range"]
    return sensor["accuracy_pct"] / 100.0 * np.abs(values) * 0.5 + 0.001 * span


def generate_readings(
    model: ProcessModel,
    result: dict,
    rng: np.random.Generator,
    sensor_faults: list[FaultEvent] | None = None,
) -> dict[str, np.ndarray]:
    """Returns {sensor_id: float array (NaN = missing)} in sorted sensor order."""
    faults_by_sensor: dict[str, list[FaultEvent]] = {}
    for f in sensor_faults or []:
        if f.kind == "SENSOR_FAULT":
            faults_by_sensor.setdefault(f.target_id, []).append(f)

    n = len(result["timestamps"])
    readings: dict[str, np.ndarray] = {}
    for sid in sorted(model.sensor_map):
        kind, key, qty = model.sensor_map[sid]
        sensor = model.sensors[sid]
        truth = true_value(result, kind, key, qty)
        lo, hi = sensor["min_range"], sensor["max_range"]
        span = hi - lo
        # Always draw noise for every sensor so the random stream does not depend on faults.
        noise = rng.normal(0.0, 1.0, n) * noise_sigma(sensor, truth)
        val = truth + noise
        if sensor["sensor_type"] == "FLOW":
            val = np.where(truth < LOW_FLOW_CUTOFF_FRACTION * span, 0.0, val)
        val = np.clip(val, lo, hi)
        fault_draws = rng.random(8)  # reserved random numbers for fault shaping
        for f in faults_by_sensor.get(sid, []):
            s, e = max(f.start_step, 0), min(f.end_step, n)
            if s >= e:
                continue
            mode = (f.mode or "").upper()
            if mode == "FLATLINE":
                val[s:e] = val[s]
            elif mode == "MISSING":
                val[s:e] = np.nan
            elif mode == "OUT_OF_RANGE":
                above = fault_draws[0] < 0.6
                val[s:e] = hi + span * (0.15 + 0.1 * fault_draws[1]) if above else lo - span * (0.1 + 0.05 * fault_draws[1])
            elif mode == "BIAS":
                val[s:e] = np.clip(val[s:e] * (1.0 - f.magnitude), lo, hi)
            elif mode == "SPIKE":
                count = max(1, min(e - s, int(f.magnitude) if f.magnitude >= 1 else 3))
                idx = np.sort(rng.choice(np.arange(s, e), size=count, replace=False))
                for j, i in enumerate(idx):
                    direction = 1 if (i + j) % 2 == 0 else -1
                    val[i] = np.clip(val[i] + direction * span * 0.35, lo, hi)
                    if abs(val[i] - truth[i]) < 0.2 * span:  # clipped at range edge -> push the other way
                        val[i] = np.clip(truth[i] - direction * span * 0.35, lo, hi)
        readings[sid] = np.round(val, 3)
    return readings


def derived_value(sensor: dict, value: float | None, tank: dict | None, step_minutes: int) -> tuple[float | None, str | None]:
    """Derived engineering value calculated from the raw reading."""
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return None, None
    st = sensor["sensor_type"]
    if st == "LEVEL" and tank is not None:
        return round(value / 100.0 * tank["capacity_m3"], 3), "m3"
    if st == "PRESSURE":
        return round(value / 0.0981, 3), "m"
    if st == "FLOW":
        return round(value * step_minutes / 60.0, 3), "m3"
    return None, None
