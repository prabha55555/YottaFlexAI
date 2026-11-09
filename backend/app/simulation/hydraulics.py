"""Simplified steady-state hydraulic calculations.

This is NOT a full industrial hydraulic network solver (no transient effects,
no looped-network Hardy-Cross/Newton solution, incompressible water only).
Each pump line is a series path whose operating point is the intersection of
the pump curve and the system curve:

    Pump curve      H_p(Q) = hf * (s^2 * H0 - k * Q^2)
    System curve    H_s(Q) = H_static + R_up * Q^2 + R_down * ((1 - f_leak) * Q)^2

where ``s`` is the speed ratio (affinity law), ``hf`` the pump health factor
(1 = new, <1 = degraded), ``f_leak`` the fraction of flow lost through a leak
located between the pump and the downstream flow meter, and R are lumped
quadratic resistances in m/(m3/h)^2. Flows are in m3/h, heads in metres of
water, pressures in bar(g).
"""
from __future__ import annotations

import math

from app.config import RHO_G_BAR_PER_M

G = 9.81
SECONDS_PER_HOUR = 3600.0
CLOSED_VALVE_THRESHOLD_PCT = 0.5


def head_to_bar(head_m: float) -> float:
    return head_m * RHO_G_BAR_PER_M


def bar_to_head(p_bar: float) -> float:
    return p_bar / RHO_G_BAR_PER_M


def pipe_resistance(length_m: float, diameter_mm: float, friction_factor: float = 0.02) -> float:
    """Darcy-Weisbach friction loss expressed as h = R * Q^2 with Q in m3/h.

    h = f * L/D * v^2 / 2g  and  v = Q / A  ->  R = 8 f L / (pi^2 g D^5)  [s^2/m^5]
    converted to (m3/h)^2 by dividing by 3600^2.
    """
    d = diameter_mm / 1000.0
    r_si = 8.0 * friction_factor * length_m / (math.pi**2 * G * d**5)
    return r_si / SECONDS_PER_HOUR**2


def restricted_resistance(r_base: float, restriction_pct: float) -> float:
    """Blockage reduces free flow area by ``restriction_pct``; the local loss
    scales with 1/(1-r)^2 (orifice-like contraction)."""
    r = min(max(restriction_pct, 0.0), 99.0) / 100.0
    return r_base / (1.0 - r) ** 2


def valve_resistance(r_full_open: float, opening_pct: float) -> float:
    """Quadratic valve characteristic: R = R100 / f^2 (f = opening fraction).
    Returns ``math.inf`` when the valve is (practically) closed."""
    if opening_pct <= CLOSED_VALVE_THRESHOLD_PCT:
        return math.inf
    f = opening_pct / 100.0
    return r_full_open / (f * f)


def pump_head(q_m3h: float, shutoff_head_m: float, curve_k: float, speed_ratio: float, health: float = 1.0) -> float:
    """H(Q) = hf * (s^2 * H0 - k Q^2), floored at zero."""
    return max(health * (speed_ratio**2 * shutoff_head_m - curve_k * q_m3h**2), 0.0)


def solve_operating_point(
    shutoff_head_m: float,
    curve_k: float,
    speed_ratio: float,
    health: float,
    static_head_m: float,
    r_up: float,
    r_down: float,
    leak_fraction: float = 0.0,
) -> float:
    """Intersect pump and system curve; returns Q (m3/h) at the pump discharge.

    hf*s^2*H0 - hf*k*Q^2 = Hs + R_up Q^2 + R_down (1-f)^2 Q^2
    -> Q = sqrt((hf*s^2*H0 - Hs) / (hf*k + R_up + R_down*(1-f)^2))
    Returns 0 when the pump cannot overcome the static head (check valve closed)
    or when a resistance is infinite (closed valve).
    """
    if speed_ratio <= 0 or health <= 0:
        return 0.0
    if math.isinf(r_up) or math.isinf(r_down):
        return 0.0
    a = health * speed_ratio**2 * shutoff_head_m - static_head_m
    if a <= 0:
        return 0.0
    b = health * curve_k + r_up + r_down * (1.0 - leak_fraction) ** 2
    return math.sqrt(a / b)


def pump_efficiency(q_m3h: float, rated_flow_m3h: float, best_efficiency: float, health: float = 1.0) -> float:
    """Parabolic efficiency curve around the best efficiency point (BEP = rated flow)."""
    if q_m3h <= 0 or rated_flow_m3h <= 0:
        return 0.0
    x = q_m3h / rated_flow_m3h
    eta = best_efficiency * (1.0 - (x - 1.0) ** 2)
    return max(eta * health, 0.0)


def hydraulic_power_kw(q_m3h: float, head_m: float) -> float:
    """P = rho g Q H  (rho = 1000 kg/m3)."""
    return 1000.0 * G * (q_m3h / SECONDS_PER_HOUR) * head_m / 1000.0


def tank_volume_step(
    volume_m3: float, q_in_m3h: float, q_out_m3h: float, q_leak_m3h: float, dt_h: float, capacity_m3: float
) -> tuple[float, float]:
    """V(t+1) = V(t) + (Qin - Qout - Qleak) * dt   (flows m3/h, dt hours).

    Returns (new_volume, overflow_m3). Volume above capacity spills (overflow)
    and volume cannot fall below zero.
    """
    v = volume_m3 + (q_in_m3h - q_out_m3h - q_leak_m3h) * dt_h
    overflow = 0.0
    if v > capacity_m3:
        overflow = v - capacity_m3
        v = capacity_m3
    return max(v, 0.0), overflow
