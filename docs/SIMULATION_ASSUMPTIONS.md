# Simulation Assumptions & Hydraulic Model

> **This is a simplified, quasi-steady-state model for monitoring and what-if
> analysis. It is not a full industrial hydraulic solver** (no transients, water
> hammer, looped-network pressure solution, cavitation physics, temperature or
> fluid property variation).

## Plant structure

Each facility consists of independent *process trains*:

```
INLET valve → Tank(stage 0) → [suction valve → PUMP → discharge valve] → Tank(stage 1) → … → OUTLET valve
```

| Facility | Trains (tanks per train) | Pumps | Tanks | Valves | Pipes | Sensors |
|---|---|---|---|---|---|---|
| FAC-001 North Water Treatment Plant | 4, 3, 3 | 7 | 10 | 20 | 34 | 54 |
| FAC-002 East Process Facility | 4, 3, 3 | 7 | 10 | 20 | 34 | 54 |
| FAC-003 South Distribution Hub | 3, 3, 2, 2 | 6 | 10 | 20 | 32 | 52 |
| **Total** | | **20** | **30** | **60** | **100** | **160** |

Telemetry: 160 sensors × 625 steps (15 min, 6.5 days) = **100,000 records** (full);
160 × 96 = 15,360 (starter).

## Units

Flow m³/h · pressure bar(g) · head m of water · level % of capacity · volume m³ ·
time step Δt in **hours** (`step_minutes / 60`). 1 m head = 0.0981 bar (ρ = 1000 kg/m³, g = 9.81 m/s²).

## Equations

| Element | Model |
|---|---|
| Pump curve | `H(Q) = hf · (s² · H0 − k · Q²)`; `s` = speed / 100 (affinity law), `hf` = health factor (1 = new) |
| Pipe friction | Darcy–Weisbach `h = R·Q²`, `R = 8 f L / (π² g D⁵) / 3600²` (Q in m³/h), f = 0.02 |
| Blockage | added contraction loss `4R·(1/(1−r)² − 1)`, `r` = restricted area fraction |
| Valve | `R = R100 / opening²`; opening ≤ 0.5 % ⇒ closed (∞) |
| Operating point | `Q = √((hf·s²·H0 − Hs) / (hf·k + R_up + R_down·(1−f)²))`; `Hs` = destination − source liquid elevation; Q = 0 if the pump cannot overcome `Hs` (check valve) |
| Leak | fraction `f` of the line flow is lost mid-way along the leaking pipe, between the pump flow meter and the delivery flow meter |
| Tank | `V(t+1) = V(t) + (Qin − Qout − Qleak)·Δt`; volume above capacity spills (overflow, recorded); never below 0 |
| Suction pressure | `Ps = 0.0981 · (z_src + h_src − R_suction·Q²)` |
| Discharge pressure | `Pd = Ps + 0.0981 · H(Q)`; a running pump against a closed valve sits at shut-off head (dead-head) |
| Delivery pressure | `0.0981 · (z_dst + h_dst + ½·R_last·Q_down²)` |
| Efficiency | parabolic around BEP (= rated flow): `η = η_max·(1 − (Q/Q_r − 1)²)·hf` |
| Power | `P = ρ g Q H / η` |

## Control & boundaries

* **Head tanks** are fed by an external supply (INLET valve) with proportional level control:
  `Q_in = clip(Q_out_requested + 0.5·(SP − L)/100·Capacity, 0, max_supply) × opening`.
* **End tanks** feed consumer demand (OUTLET valve): `Q_out = nominal × diurnal(t) × demand_factor × opening`,
  where `diurnal(t) = 1 + 0.18·sin(2π(h−9)/24) + 0.05·sin(2π(h−3)/12) + AR(1) noise (σ = 0.02, φ = 0.9)`.
* **Intermediate tanks** self-regulate through the static head term of the pump curve
  (higher source level ⇒ more flow out; higher destination level ⇒ less flow in).
* Pumps cannot draw a tank below 2 % of capacity; when starved their flow is scaled down
  and developed head collapses proportionally (simple dry-run/cavitation approximation).
* Pumps were *calibrated by the generator* so that at 50 % tank levels and the configured
  discharge-valve opening every pump in a train delivers the train's design flow.

## Sensors

* Reading = true value + N(0, σ), `σ = accuracy% · |value| / 2 + 0.1 % · span`.
* Clipped to instrument range (transmitters saturate), rounded to 3 decimals.
* Flow meters: low-flow cut-off below 0.5 % of span reads 0.
* Faults: `FLATLINE` (stuck at first value), `SPIKE` (±35 % span single samples),
  `OUT_OF_RANGE` (fixed value above/below range), `MISSING` (NULL value), `BIAS`
  (reading × (1 − magnitude)).

## Fault injection rules (synthetic dataset)

Per facility (`app/generation/faults.py`):

| Fault | Target | Magnitude | Duration (fraction of horizon) |
|---|---|---|---|
| PIPE_LEAK | transfer main of a random line | 8–20 % of line flow | 6–10 % |
| PIPE_BLOCKAGE | transfer main of a different line | 40–65 % area restriction | 5–8 % |
| PUMP_DEGRADATION | pump of a third line | health 0.68–0.85 | 8–14 % |
| SENSOR_FAULT ×3 | sensors not on faulted lines; modes rotate FLATLINE→SPIKE→OUT_OF_RANGE→MISSING→BIAS | BIAS 10–15 % on a delivery flow meter | 2–8 % |
| Operator throttle (FAC-001 only) | one OUTLET valve set to 15 % | — | 10–14 % |

**Detection-limit tests (full scale only):** FAC-001 leak 6 % (just above the 5 % threshold),
FAC-002 leak 3.5 % (below), FAC-003 pump health 0.93 (7 % head loss, below the 10 % threshold),
FAC-001 delivery-meter BIAS 4 % (below). These are labelled `detection_limit_test: true`
in the ground truth and are *expected* misses for the below-threshold cases.

Ground truth `TANK_OVERCAPACITY` labels come from the **true** level (≥ 95 % for ≥ 2 samples),
whatever caused it (operator throttle or a blockage backing up a tank).

## Simulation studio

* Horizon 8–672 steps; step 5/10/15/30/60 min; default seed 20261022, 96 × 15 min.
* **Operational parameters** (known to the detector): pump speed, pump availability, valve opening,
  tank initial level, outlet flow demand, demand factor, operating mode (multiplies demand and pump speed).
* **Fault parameters** (hidden from the detector): pipe leaks, pipe restrictions, pump health, sensor faults.
  Active from `fault_start_step` (default steps/4) to the end of the run.
* Scenario presets pick deterministic targets (first pump line of the facility); user parameters override them.
* Each run stores: original configuration snapshot, user + resolved parameters, effective configuration,
  injected faults, KPIs, measured & true mass balance, time series, sensor readings, assumptions,
  validation errors, input hash and duration. Runs are never overwritten.
* Baseline: by default a `NORMAL` run with the same seed / horizon and **no** modifications is executed and
  linked via `baseline_simulation_id` for comparison.
