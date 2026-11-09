"""Anomaly detection rules: leak, blockage, pump degradation, sensor faults, overcapacity."""
from __future__ import annotations

from datetime import datetime

import numpy as np
import pytest

from app.anomaly_detection.detector import Detector, runs
from app.config import DEFAULT_SEED
from app.generation.generator import generate_dataset
from app.simulation.engine import FaultEvent, OperatingSettings, run_process
from app.simulation.sensors import generate_readings

T0 = datetime(2026, 10, 22)
N = 64


@pytest.fixture(scope="module")
def model():
    return generate_dataset(DEFAULT_SEED, "tiny").models["FAC-002"]


def detect(model, faults, settings=None, seed=11):
    settings = settings or OperatingSettings()
    res = run_process(model, N, 15, T0, settings, faults, np.random.default_rng(seed))
    rd = generate_readings(model, res, np.random.default_rng(seed + 1), [f for f in faults if f.kind == "SENSOR_FAULT"])
    return Detector(model, settings).detect(rd, res["timestamps"], 15).anomalies


def of_type(anoms, t):
    return [a for a in anoms if a["anomaly_type"] == t]


def test_normal_operation_has_no_fault_anomalies(model):
    anoms = detect(model, [])
    assert not [a for a in anoms if a["anomaly_type"] in ("LEAK", "BLOCKAGE", "PUMP_DEGRADATION", "SENSOR_FAULT")]


def test_leak_detection(model):
    ln = model.lines[1]
    anoms = detect(model, [FaultEvent("PIPE_LEAK", ln.last_pipe_id, 16, N, 0.15)])
    leaks = of_type(anoms, "LEAK")
    assert leaks and leaks[0]["equipment_id"] == ln.last_pipe_id
    a = leaks[0]
    assert a["severity"] == "HIGH" and a["detection_rule"] == "LEAK_FLOW_IMBALANCE"
    assert a["observed_value"] == pytest.approx(15, abs=2)
    for field in ("facility_id", "equipment_id", "anomaly_type", "severity", "detected_at", "detection_rule",
                  "observed_value", "expected_value", "threshold", "recommended_action"):
        assert a[field] is not None
    assert not of_type(anoms, "PUMP_DEGRADATION")


def test_blockage_detection(model):
    ln = model.lines[2]
    anoms = detect(model, [FaultEvent("PIPE_BLOCKAGE", ln.last_pipe_id, 16, N, 60.0)])
    blk = of_type(anoms, "BLOCKAGE")
    assert blk and blk[0]["equipment_id"] == ln.last_pipe_id
    assert blk[0]["observed_value"] < blk[0]["threshold"] < blk[0]["expected_value"]
    assert not of_type(anoms, "LEAK") and not of_type(anoms, "PUMP_DEGRADATION")


def test_pump_degradation_detection(model):
    ln = model.lines[0]
    anoms = detect(model, [FaultEvent("PUMP_DEGRADATION", ln.pump_id, 16, N, 0.75)])
    deg = of_type(anoms, "PUMP_DEGRADATION")
    assert deg and deg[0]["equipment_id"] == ln.pump_id
    assert deg[0]["evidence"]["head_deficit_pct"] == pytest.approx(25, abs=3)
    assert deg[0]["severity"] == "HIGH"
    assert not of_type(anoms, "BLOCKAGE")


@pytest.mark.parametrize("mode,rule", [("FLATLINE", "SENSOR_FLATLINE"), ("SPIKE", "SENSOR_SPIKE"),
                                       ("OUT_OF_RANGE", "SENSOR_OUT_OF_RANGE"), ("MISSING", "SENSOR_MISSING")])
def test_sensor_fault_detection(model, mode, rule):
    sid = model.lines[3].sensors["p_discharge"]
    mag = 3 if mode == "SPIKE" else 0
    anoms = detect(model, [FaultEvent("SENSOR_FAULT", sid, 20, 40, mag, mode)])
    sf = [a for a in of_type(anoms, "SENSOR_FAULT") if a["sensor_id"] == sid]
    assert sf and sf[0]["detection_rule"] == rule and sf[0]["category"] == "SENSOR"
    # faulty pressure data must not be reported as a process fault on that pump
    assert not [a for a in anoms if a["anomaly_type"] in ("PUMP_DEGRADATION", "BLOCKAGE")
                and a["equipment_id"] in (model.lines[3].pump_id, model.lines[3].last_pipe_id)]


def test_flow_meter_bias_is_sensor_fault_not_leak(model):
    ln = model.lines[1]
    sid = ln.sensors["flow_down"]
    anoms = detect(model, [FaultEvent("SENSOR_FAULT", sid, 16, N, 0.12, "BIAS")])
    assert not of_type(anoms, "LEAK"), "meter bias must not be labelled as a process leak"
    rec = [a for a in anoms if a["detection_rule"] == "FLOW_RECONCILIATION"]
    assert rec and rec[0]["sensor_id"] == sid


def test_tank_overcapacity_detection(model):
    ob = model.outlets[0]
    settings = OperatingSettings(valve_opening_pct={ob.valve_id: 5.0}, tank_initial_level_pct={ob.tank_id: 85.0})
    anoms = detect(model, [], settings)
    tk = [a for a in of_type(anoms, "TANK_OVERCAPACITY") if a["equipment_id"] == ob.tank_id]
    assert tk and tk[0]["severity"] in ("HIGH", "CRITICAL")


def test_detector_never_sees_fault_parameters(model):
    """Detector API accepts only model + known settings + readings."""
    import inspect
    sig = inspect.signature(Detector.detect)
    assert "faults" not in sig.parameters and "ground_truth" not in sig.parameters


def test_runs_helper():
    m = np.array([0, 1, 1, 0, 1, 0, 0, 1, 1, 1], bool)
    assert runs(m, 2, 0) == [(1, 2), (7, 9)]
    assert runs(m, 2, 1) == [(1, 4), (7, 9)]


def test_starved_downstream_pump_is_not_reported_as_degraded(model):
    """A blockage that drains the next tank makes the downstream pump run dry; its head loss
    must not be classified as pump degradation (regression for a simulation false positive)."""
    ln = model.lines[0]
    settings = OperatingSettings()
    res = run_process(model, 96, 15, T0, settings, [FaultEvent("PIPE_BLOCKAGE", ln.last_pipe_id, 0, 96, 60.0)],
                      np.random.default_rng(5))
    rd = generate_readings(model, res, np.random.default_rng(6))
    anoms = Detector(model, settings).detect(rd, res["timestamps"], 15).anomalies
    assert of_type(anoms, "BLOCKAGE")
    assert not of_type(anoms, "PUMP_DEGRADATION")
