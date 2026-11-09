# Validation Summary

All numbers below were produced by the commands shown, on seed **20261022**, and can be
reproduced exactly. Nothing here is estimated or hand-entered.

```bash
cd backend
python -m scripts.generate_data --seed 20261022 --scale full   # data + detection + evaluation
python -m scripts.run_scenarios                                 # 8 scenarios × 3 facilities
python -m scripts.run_evaluation                                # detection + data quality
python -m scripts.run_negative_scenarios                        # 5 negative cases
python -m pytest -q                                             # automated tests
```

## 1. Dataset

| Item | Starter | Full |
|---|---|---|
| Facilities / pumps / tanks / valves / pipes / sensors | 3 / 20 / 30 / 60 / 100 / 160 | 3 / 20 / 30 / 60 / 100 / 160 |
| Time steps (15 min) | 96 (1 day) | 625 (6.5 days) |
| Telemetry records | 15,360 | **100,000** |
| Ground-truth labels | 18 | 23 (incl. 4 detection-limit tests) |
| Dataset fingerprint (SHA-256 of all export hashes) | `75fdecdf…` | `a0e9cdeb47728f6737040f01bf3d5921aa26a3b202cf5c5fa7b86e37ee254171` |

Reproducibility: regenerating with the same seed and scale gives identical per-file SHA-256
hashes (checked across separate runs and by `test_generation_is_deterministic`); a different
seed changes the telemetry hash (`test_different_seed_changes_data`).

## 2. Data quality (full dataset)

| Metric | Value |
|---|---|
| Primary-key integrity | 100 % (0 duplicate IDs, 0 format violations) |
| Foreign-key integrity | 100 % (0 errors over 100,370 checked relationships, incl. polymorphic pipe/sensor references and SQLite `foreign_key_check`) |
| Duplicate count | 0 (names unique per facility, pipe connections, telemetry keys) |
| Missing values | 0.042 % of telemetry (42 NULL readings — all from injected `MISSING` sensor faults) |
| Topology validity | 3 / 3 facilities valid (0 errors, 0 warnings; 3, 3 and 4 connected trains) |
| Out-of-range readings | 78 readings on 4 sensors (all injected `OUT_OF_RANGE` / spike faults) |
| Tank capacity violations | 0 |
| Mass balance (full period, measured) | FAC-001 2.38 % WARNING (process imbalance: real overflow + leak), FAC-002 0.59 % BALANCED, FAC-003 1.08 % BALANCED; mean \|error\| 1.35 % |
| Mass balance (24 h windows) | 4 windows above tolerance — each coincides with an injected leak or the operator-caused overflow |
| Simulation success rate | 100 % of completed-type runs (failed runs only appear when invalid inputs are submitted on purpose; they are recorded as FAILED and counted) |
| True model mass-balance closure | 0.000 m³ (every simulation) |

## 3. Detection evaluation (telemetry scan vs ground truth, full dataset)

Window-based confusion matrix: unit = (issue type, asset, 6 h window); 27 windows; 6,750 units.

| Issue type | TP | FP | TN | FN | Precision | Recall | F1 | Events detected | Mean latency | Severity agreement |
|---|---|---|---|---|---|---|---|---|---|---|
| LEAK | 12 | 0 | — | 3 | 1.000 | 0.800 | 0.889 | 4 / 5 | 45 min | 0.75 |
| BLOCKAGE | 8 | 0 | — | 0 | 1.000 | 1.000 | 1.000 | 3 / 3 | 45 min | 1.00 |
| PUMP_DEGRADATION | 12 | 0 | — | 3 | 1.000 | 0.800 | 0.889 | 3 / 4 | 45 min | 1.00 |
| SENSOR_FAULT | 15 | 0 | — | 3 | 1.000 | 0.833 | 0.909 | 9 / 10 | 58 min | 1.00 |
| TANK_OVERCAPACITY | 3 | 0 | — | 0 | 1.000 | 1.000 | 1.000 | 1 / 1 | 15 min | 1.00 |
| **Overall** | **50** | **0** | **6,691** | **9** | **1.000** | **0.848** | **0.917** | 20 / 23 | | |

**Missed events (3) are the below-threshold detection-limit tests, by design:**

| Label | Injected fault | Threshold | Outcome |
|---|---|---|---|
| GT-0022 | 3.5 % leak on PIPE-043 | 5 % flow imbalance | missed (expected) |
| GT-0001 | PUMP-019 health 0.93 (7 % head loss) | 10 % head deficit | missed (expected) |
| GT-0016 | 4 % bias on delivery meter SNS-015 | 5 % flow imbalance | missed (expected) |
| GT-0018 | 6 % leak on PIPE-013 (just above threshold) | 5 % | **detected** |

The remaining 6 window-level false negatives are boundary windows at the start of
detected events: the detector needs ≥ 4 samples (1 h) of persistence, so a label that
begins in the last minutes of a 6 h window is only flagged in the next window.

Severity disagreement (LEAK 0.75): one 20.0 % leak (expected CRITICAL at ≥ 20 %) was
measured at 19.99 % imbalance and rated HIGH.

**Sensor faults labelled as process faults: 0.** The injected 12.7 % BIAS (SNS-090, GT-0015) on a delivery flow
meter (which a naive rule would call a leak) was classified as `SENSOR_FAULT` by the
flow/tank-level reconciliation.

Caveat: thresholds were designed against the documented synthetic noise model, so these
figures describe performance on this synthetic data only (see KNOWN_LIMITATIONS.md).

## 4. Scenario runs (simulation engine, 96 × 15 min, every facility)

24 runs + 21 linked baselines, all COMPLETED; every scenario raised its expected anomaly type.

| Scenario | Expected detection | FAC-001 | FAC-002 | FAC-003 |
|---|---|---|---|---|
| NORMAL | none | none ✔ | none ✔ | none ✔ |
| LEAKAGE | LEAK | LEAK ✔ | LEAK + MASS_BALANCE ✔ | LEAK ✔ |
| BLOCKAGE | BLOCKAGE | BLOCKAGE (+ downstream low level) ✔ | ✔ | ✔ |
| PUMP_DEGRADATION | PUMP_DEGRADATION | ✔ | ✔ | ✔ |
| SENSOR_MALFUNCTION | SENSOR_FAULT | 2 (bias via reconciliation + flatline) ✔ | ✔ | ✔ |
| HIGH_DEMAND | operational impact | demand served 91.0 %, low levels | 89.9 % | 90.3 % |
| VALVE_CLOSURE | ABNORMAL_FLOW (dead-head) | ✔ | ✔ | ✔ |
| TANK_OVERCAPACITY | TANK_OVERCAPACITY | ✔ + MASS_BALANCE (1,445 m³ overflow) | ✔ | ✔ |

A false positive found during this verification — a pump starved by an upstream blockage was
reported as `PUMP_DEGRADATION` — was fixed (head-deficit rule suppressed while the suction
tank is at/below its low-level alarm) and covered by a regression test.

## 5. Negative scenarios (`backend/negative_cases/`, never loaded into the baseline DB)

| Case | Validator | Result |
|---|---|---|
| NEG-001 Pipe references a missing node | topology | FAILED as expected — `MISSING_NODE`: "Pipe PIPE-902 references missing node(s): PUMP-999" (+ isolated-node findings) |
| NEG-002 Tank level exceeds capacity | tank readings | FAILED — `VOLUME_EXCEEDS_CAPACITY` for 104.2 % and 112 % (896 m³ in an 800 m³ tank) |
| NEG-003 Flow conservation violated | mass balance | FAILED — residual 290 m³ = 12.08 % > 2 % tolerance, `PROCESS_IMBALANCE` |
| NEG-004 Simulation output lacks input configuration | simulation record | FAILED — `MISSING_INPUT_CONFIGURATION` for original_config, modified_parameters, effective_config |
| NEG-005 Sensor fault labelled as process fault | classification | FAILED — `MISCLASSIFIED_SENSOR_FAULT`: tank level matches the upstream meter (residual ≈ 6 m³) vs the biased meter (≈ 191 m³) |

**5 / 5 caught.** The same rules also reject live API writes: a pipe to a missing node → 422
`MISSING_NODE`; a tank level > 100 % → 422; invalid simulation parameters → 422 with field
errors and a persisted FAILED run.

## 6. Automated tests

`python -m pytest -q` → **43 passed** (isolated temporary database), covering database
relationships, deterministic IDs, 100k generation, reproducibility, topology validation, pump /
valve / pipe / tank calculations, mass-balance closure, leak, blockage, pump degradation, all
sensor-fault modes, bias-vs-leak classification, tank overcapacity, simulation reproducibility &
immutability, all scenarios, failed-run recording, alarm lifecycle & history, evaluation counts,
negative scenarios, exports, dashboard and analytics endpoints.

## 7. End-to-end smoke test and static checks

* `python -m scripts.smoke_test` against the running API (and through the frontend proxy):
  **102/102 passed** — 77 API calls (every endpoint, filters, exports, CRUD incl. rejections,
  simulation + comparison, alarm lifecycle, negative cases) and 25 data checks.
* Starting both servers with exactly the README commands was re-verified from a clean state.
* `ruff check app scripts tests` — no findings; `tsc --noEmit` — no errors; `npm run build` — succeeds.

## 8. Manual frontend verification

Performed in a real browser against the running stack (backend :8000, frontend :5173):

* All 12 routes rendered with backend data and **no console errors**.
* Simulation run from the UI form (Blockage, demand factor 1.2) → new `SIM-2026-000046`, KPIs,
  measured vs true mass balance, charts and detected anomalies displayed; deep link `?id=` works.
* Alarm ALM-000005 acknowledged and resolved from the UI; actor, note and history persisted.
* Equipment CRUD: tank creation blocked client-side at 120 % initial level, created at 40 %,
  then deleted; deleting PUMP-001 refused with the list of referencing pipes and sensors.
* CSV and JSON exports for telemetry, anomalies, alarms and simulations (time series, readings,
  full JSON) return correct content types and filenames.
* Issue found and fixed: chart helper components were not direct Recharts children, so axes,
  grid, tooltips and legends were silently dropped; helpers are now called as functions.
