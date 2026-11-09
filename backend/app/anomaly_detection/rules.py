"""Transparent, documented detection thresholds and severity mappings.

The same severity functions are used to derive the *expected severity* in the
ground-truth file (from the injected fault magnitude), so evaluation compares
like with like. Ground truth is never used as detector input.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Thresholds:
    # Sensor validation
    flatline_steps: int = 8  # identical readings for >= 2 h (15-min steps)
    spike_fraction_of_span: float = 0.20
    missing_persistence: int = 2
    # Process rules
    persistence_steps: int = 4  # condition must hold >= 1 h
    leak_imbalance_fraction: float = 0.05  # (Q_up - Q_down)/Q_up
    min_flow_fraction_of_rated: float = 0.10
    blockage_flow_fraction: float = 0.80  # observed < 80 % of model-expected flow
    blockage_pressure_rise_bar: float = 0.15
    degradation_head_ratio: float = 0.90  # measured head < 90 % of pump-curve head
    deadhead_flow_fraction: float = 0.05
    pressure_warning_fraction: float = 0.90  # of pipe max pressure
    low_suction_bar: float = 0.05
    tank_high_persistence: int = 2


THRESHOLDS = Thresholds()

ANOMALY_TYPES = (
    "LEAK",
    "BLOCKAGE",
    "PUMP_DEGRADATION",
    "SENSOR_FAULT",
    "TANK_OVERCAPACITY",
    "ABNORMAL_FLOW",
    "ABNORMAL_PRESSURE",
    "ABNORMAL_LEVEL",
    "MASS_BALANCE",
)

# Issue types covered by ground truth and evaluation
EVALUATED_TYPES = ("LEAK", "BLOCKAGE", "PUMP_DEGRADATION", "SENSOR_FAULT", "TANK_OVERCAPACITY")


def leak_severity(leak_fraction: float) -> str:
    pct = leak_fraction * 100
    if pct >= 20:
        return "CRITICAL"
    if pct >= 10:
        return "HIGH"
    return "MEDIUM"


def blockage_severity(flow_reduction_fraction: float) -> str:
    pct = flow_reduction_fraction * 100
    if pct >= 60:
        return "CRITICAL"
    if pct >= 40:
        return "HIGH"
    return "MEDIUM"


def degradation_severity(head_deficit_fraction: float) -> str:
    pct = head_deficit_fraction * 100
    if pct >= 30:
        return "CRITICAL"
    if pct >= 20:
        return "HIGH"
    return "MEDIUM"


SENSOR_FAULT_SEVERITY = {
    "SPIKE": "LOW",
    "FLATLINE": "MEDIUM",
    "MISSING": "MEDIUM",
    "BIAS": "MEDIUM",
    "INCONSISTENT": "MEDIUM",
    "OUT_OF_RANGE": "HIGH",
}


def tank_severity(max_level_pct: float) -> str:
    return "CRITICAL" if max_level_pct >= 99.5 else "HIGH"


RECOMMENDED_ACTIONS = {
    "LEAK": "Dispatch field crew to inspect the pipe between the pump discharge and downstream flow meter; "
            "isolate the segment if loss is confirmed.",
    "BLOCKAGE": "Inspect the line for partial blockage (strainer, debris, partially closed valve); "
                "schedule pigging/flushing and verify valve positions.",
    "PUMP_DEGRADATION": "Schedule pump inspection (impeller wear, cavitation damage, seal/wear-ring clearance); "
                        "compare against pump curve after maintenance.",
    "SENSOR_FAULT": "Check transmitter wiring, power and calibration; treat readings as unreliable and use "
                    "redundant measurements until the instrument is verified.",
    "TANK_OVERCAPACITY": "Reduce inflow (throttle feed pump / inlet valve) or increase outflow; verify outlet "
                         "valve position and overflow line.",
    "ABNORMAL_FLOW": "Verify operating point against pipe capacity and pump status; check valve positions.",
    "ABNORMAL_PRESSURE": "Verify pressure against pipe rating; check for closed downstream valves or "
                         "low suction level (cavitation risk).",
    "ABNORMAL_LEVEL": "Check upstream supply and downstream demand; protect pumps from dry running.",
    "MASS_BALANCE": "Reconcile facility inflow, outflow and storage; inspect for unmetered losses or "
                    "instrument drift.",
}

RULE_DESCRIPTIONS = {
    "SENSOR_MISSING": "No value received for >= 2 consecutive expected timestamps.",
    "SENSOR_OUT_OF_RANGE": "Reading outside the instrument's calibrated range [min_range, max_range].",
    "SENSOR_FLATLINE": "Identical readings for >= 8 consecutive samples while not at a range limit.",
    "SENSOR_SPIKE": "Single-sample deviation > 20 % of span from the centred 5-sample median.",
    "FLOW_RECONCILIATION": "Pump-discharge and pipe-end flow disagree by > 5 %, but the tank level change "
                           "matches the other meter: the disagreeing meter is faulty (not a process leak).",
    "LEAK_FLOW_IMBALANCE": "Pump-discharge flow exceeds pipe-end flow by > 5 % for >= 1 h, and the downstream "
                           "tank level change confirms the lower (pipe-end) flow.",
    "BLOCKAGE_FLOW_PRESSURE": "Flow < 80 % of model-expected flow AND pump discharge pressure > expected + "
                              "0.15 bar for >= 1 h (pump pushed left on its curve by added resistance).",
    "PUMP_HEAD_DEFICIT": "Measured pump head (Pd - Ps) < 90 % of the pump-curve head at the measured flow "
                         "for >= 1 h.",
    "TANK_HIGH_LEVEL": "Tank level >= high alarm limit for >= 2 samples.",
    "TANK_LOW_LEVEL": "Tank level <= low alarm limit for >= 2 samples.",
    "PUMP_DEADHEAD": "Pump running with < 5 % of rated flow against a closed valve.",
    "PUMP_NO_DELIVERY": "Pump commanded to run but neither flow nor head is developed (trip / dry run).",
    "PIPE_OVERPRESSURE": "Pump discharge pressure >= 90 % of the discharge pipe pressure rating.",
    "LOW_SUCTION_PRESSURE": "Suction pressure below 0.05 bar(g) while running (cavitation risk).",
    "FLOW_ABOVE_CAPACITY": "Measured flow above the pipe's maximum design flow.",
    "FACILITY_MASS_BALANCE": "Facility inflow - outflow - storage change exceeds the balance tolerance.",
}
