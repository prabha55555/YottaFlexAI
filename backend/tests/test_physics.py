"""Pump, tank, valve and pipe calculations; mass balance closure."""
from __future__ import annotations

import math
from datetime import datetime

import numpy as np
import pytest

from app.config import DEFAULT_SEED
from app.generation.generator import generate_dataset
from app.services.mass_balance import facility_balance, status_for, true_balance
from app.simulation import hydraulics as hy
from app.simulation.engine import FaultEvent, OperatingSettings, run_process
from app.simulation.sensors import generate_readings

T0 = datetime(2026, 10, 22)


@pytest.fixture(scope="module")
def model():
    return generate_dataset(DEFAULT_SEED, "tiny").models["FAC-001"]


def test_pump_curve_formula():
    # H(Q) = H0 - k Q^2 at full speed and health
    assert hy.pump_head(100, 50, 0.001, 1.0) == pytest.approx(50 - 0.001 * 100**2)
    # affinity law: shut-off head scales with speed^2
    assert hy.pump_head(0, 50, 0.001, 0.9) == pytest.approx(50 * 0.81)
    # degradation reduces head proportionally
    assert hy.pump_head(100, 50, 0.001, 1.0, health=0.8) == pytest.approx(0.8 * 40)
    assert hy.pump_head(1000, 50, 0.001, 1.0) == 0.0


def test_operating_point_intersects_pump_and_system_curves():
    h0, k, hs, r = 40.0, 0.0008, 10.0, 0.0012
    q = hy.solve_operating_point(h0, k, 1.0, 1.0, hs, r, 0.0)
    assert hy.pump_head(q, h0, k, 1.0) == pytest.approx(hs + r * q * q, rel=1e-9)
    assert hy.solve_operating_point(h0, k, 1.0, 0.8, hs, r, 0.0) < q  # degraded pump delivers less
    assert hy.solve_operating_point(h0, k, 1.0, 1.0, 45.0, r, 0.0) == 0.0  # cannot beat static head


def test_valve_closure_and_restriction_increase_resistance():
    assert math.isinf(hy.valve_resistance(1e-4, 0.0))
    assert hy.valve_resistance(1e-4, 50) == pytest.approx(4e-4)
    assert hy.solve_operating_point(40, 0.0008, 1.0, 1.0, 10, hy.valve_resistance(1e-4, 0), 0) == 0.0
    assert hy.restricted_resistance(1.0, 50) == pytest.approx(4.0)
    assert hy.pipe_resistance(100, 150, 0.02) > hy.pipe_resistance(100, 200, 0.02) > 0


def test_tank_volume_equation_and_overflow():
    v, spill = hy.tank_volume_step(500, 120, 100, 5, 0.25, 1000)
    assert v == pytest.approx(500 + (120 - 100 - 5) * 0.25) and spill == 0
    v, spill = hy.tank_volume_step(990, 200, 0, 0, 0.25, 1000)
    assert v == 1000 and spill == pytest.approx(40)
    v, _ = hy.tank_volume_step(1, 0, 100, 0, 1.0, 1000)
    assert v == 0.0


def test_process_mass_balance_closes_exactly(model):
    faults = [FaultEvent("PIPE_LEAK", model.lines[0].last_pipe_id, 5, 40, 0.15)]
    res = run_process(model, 48, 15, T0, OperatingSettings(), faults, np.random.default_rng(1))
    tb = true_balance(model, res)
    assert abs(tb["closure_error_m3"]) < 1e-6
    assert tb["true_leak_m3"] > 0


def test_valve_closure_reduces_downstream_flow(model):
    ln = model.lines[0]
    dv = [i for k, i in ln.discharge_path if k == "VALVE"][0]
    base = run_process(model, 24, 15, T0, OperatingSettings())
    closed = run_process(model, 24, 15, T0, OperatingSettings(valve_opening_pct={dv: 0.0}))
    assert closed["lines"][ln.pump_id]["q_down"].max() == 0.0
    assert base["lines"][ln.pump_id]["q_down"].mean() > 10
    # deadhead: pump keeps running at shut-off head -> higher discharge pressure
    assert closed["lines"][ln.pump_id]["p_discharge"].mean() > base["lines"][ln.pump_id]["p_discharge"].mean()


def test_blockage_reduces_flow_and_raises_upstream_pressure(model):
    ln = model.lines[0]
    f = [FaultEvent("PIPE_BLOCKAGE", ln.last_pipe_id, 0, 24, 60.0)]
    base = run_process(model, 24, 15, T0, OperatingSettings())
    blk = run_process(model, 24, 15, T0, OperatingSettings(), f)
    assert blk["lines"][ln.pump_id]["q_down"].mean() < 0.85 * base["lines"][ln.pump_id]["q_down"].mean()
    assert blk["lines"][ln.pump_id]["p_discharge"].mean() > base["lines"][ln.pump_id]["p_discharge"].mean()


def test_tank_level_responds_to_inflow_and_outflow(model):
    ob = model.outlets[0]
    res = run_process(model, 48, 15, T0, OperatingSettings(valve_opening_pct={ob.valve_id: 0.0}))
    lvl = res["tanks"][ob.tank_id]["level_pct"]
    assert lvl[-1] > lvl[0] + 5  # outflow stopped -> tank fills


def test_measured_mass_balance_status(model):
    assert status_for(1.0, 2.0) == "BALANCED"
    assert status_for(3.0, 2.0) == "WARNING"
    assert status_for(5.0, 2.0) == "EXCEPTION"
    res = run_process(model, 48, 15, T0, OperatingSettings(), [], np.random.default_rng(3))
    readings = generate_readings(model, res, np.random.default_rng(4))
    mb = facility_balance(model, readings, 15)
    assert mb["status"] == "BALANCED", mb
    leak = [FaultEvent("PIPE_LEAK", model.lines[0].last_pipe_id, 0, 48, 0.3)]
    res = run_process(model, 48, 15, T0, OperatingSettings(), leak, np.random.default_rng(3))
    readings = generate_readings(model, res, np.random.default_rng(4))
    mb = facility_balance(model, readings, 15, tolerance_pct=1.0)
    assert mb["estimated_leakage_m3"] > 0
    assert mb["classification"] in ("PROCESS_IMBALANCE", "OK")
