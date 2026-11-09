# Anomaly Detection Rules

Implementation: `backend/app/anomaly_detection/detector.py`, thresholds in `rules.py`.
The detector receives **readings + known configuration** only. Ground-truth labels and
injected fault parameters are never inputs (enforced by the function signature and a test).

## Pipeline

1. **Sensor validation** — each reading is checked; invalid readings are masked (NaN) for
   all process rules so an instrument fault cannot be reported as a process fault.
2. **Process rules** per pump line, tank and boundary, using a model-based *expected* value
   computed from the pump curve, the known speed/valve settings and the **measured** tank levels.
3. **Flow reconciliation** — a three-way balance (pump meter, delivery meter, tank level
   change) decides whether a flow imbalance is a real leak or a faulty meter.
4. **Event merging** — contiguous flagged samples (gaps ≤ 1 sample bridged) with the required
   persistence become one anomaly with start, end and detection time
   (`detected_at = start + persistence − 1` samples).
5. **Facility mass balance** per 24 h window (telemetry scan) or per run (simulation).

## Rules

| Rule id | Type | Condition | Persistence | Severity |
|---|---|---|---|---|
| `SENSOR_MISSING` | SENSOR_FAULT | value NULL / timestamp absent | ≥ 2 samples | MEDIUM |
| `SENSOR_OUT_OF_RANGE` | SENSOR_FAULT | value < min_range or > max_range | 1 | HIGH |
| `SENSOR_FLATLINE` | SENSOR_FAULT | ≥ 8 identical consecutive values, not at a range limit (zero flow / full tank are legitimate flat values) | 8 | MEDIUM |
| `SENSOR_SPIKE` | SENSOR_FAULT | \|x − centred 5-sample median\| > 20 % span | 1 | LOW |
| `FLOW_RECONCILIATION` | SENSOR_FAULT (category SENSOR) | \|Q_up − Q_down\|/Q_up > 5 % **and** the tank level change matches the *other* meter better | 4 | MEDIUM |
| `LEAK_FLOW_IMBALANCE` | LEAK | (Q_up − Q_down)/Q_up > 5 % with Q_up > 10 % rated **and** downstream tank level confirms the lower delivered flow | 4 (1 h) | <10 % MEDIUM · 10–20 % HIGH · ≥20 % CRITICAL |
| `BLOCKAGE_FLOW_PRESSURE` | BLOCKAGE | Q_obs < 80 % of Q_expected **and** Pd > Pd_expected + 0.15 bar **and** no leak-type imbalance | 4 | reduction <40 % MEDIUM · 40–60 % HIGH · ≥60 % CRITICAL |
| `PUMP_HEAD_DEFICIT` | PUMP_DEGRADATION | measured head (Pd − Ps)/0.0981 < 90 % of curve head at measured flow, Q > 20 % rated; suppressed while the suction tank is at/below its low-level alarm (head loss from dry running is a supply problem, reported as `TANK_LOW_LEVEL`) | 4 | deficit <20 % MEDIUM · 20–30 % HIGH · ≥30 % CRITICAL |
| `TANK_HIGH_LEVEL` | TANK_OVERCAPACITY | level ≥ high alarm (95 %) | 2 | HIGH; peak ≥ 99.5 % (overflowing) CRITICAL |
| `TANK_LOW_LEVEL` | ABNORMAL_LEVEL | level ≤ low alarm (10 %) | 2 | MEDIUM |
| `PUMP_DEADHEAD` | ABNORMAL_FLOW (OPERATIONAL) | pump running, Q < 5 % rated, head > 80 % shut-off, a line valve known closed | 4 | HIGH |
| `PUMP_NO_DELIVERY` | ABNORMAL_FLOW (OPERATIONAL) | pump running, Q < 5 % rated, head < 20 % shut-off, model expects flow | 4 | HIGH |
| `PIPE_OVERPRESSURE` | ABNORMAL_PRESSURE | Pd ≥ 90 % of discharge pipe rating | 2 | HIGH; ≥ 100 % CRITICAL |
| `LOW_SUCTION_PRESSURE` | ABNORMAL_PRESSURE | Ps < 0.05 bar(g) while running | 4 | MEDIUM |
| `FLOW_ABOVE_CAPACITY` | ABNORMAL_FLOW | flow > pipe max design flow | 4 | HIGH |
| `FACILITY_MASS_BALANCE` | MASS_BALANCE | \|inflow − outflow − ΔV\| / inflow > 2 × tolerance (EXCEPTION) | window | MEDIUM; > 3 × tol HIGH |

## Why the rules separate the fault classes

| Situation | Q_up | Q_down | Pd vs expected | Head ratio | Tank reconciliation | Result |
|---|---|---|---|---|---|---|
| Leak | ≈/↑ | ↓ | ≈/↓ | ≈ 1 | dst tank matches Q_down | LEAK |
| Delivery meter under-reads | ≈ | ↓ (reading) | ≈ | ≈ 1 | dst tank matches Q_up | SENSOR_FAULT |
| Blockage | ↓ | ↓ | **↑** (pump pushed left on curve) | ≈ 1 | consistent | BLOCKAGE |
| Pump degradation | ↓ | ↓ | ↓ | **< 0.9** | consistent | PUMP_DEGRADATION |
| Closed valve (known) | 0 | 0 | ↑ to shut-off | — | — | PUMP_DEADHEAD (operational) |

## Mass balance classification

`services/mass_balance.py`: residual = inflow − outflow − ΔV (from level sensors).
Status BALANCED (≤ tol, default 2 %), WARNING (≤ 2 tol), EXCEPTION (> 2 tol).
Non-balanced windows are classified `MEASUREMENT_FAULT` when any boundary instrument is invalid
or was attributed a fault by reconciliation, otherwise `PROCESS_IMBALANCE`; estimated leakage is
reported only for process imbalance. Per-line balances (pump meter vs delivery meter) localise losses.

## Every anomaly record contains

`id` (ANM-000001), `facility_id`, `equipment_type`, `equipment_id`, `sensor_id`, `anomaly_type`,
`category` (PROCESS/SENSOR/OPERATIONAL), `severity`, `detected_at`, `start_time`, `end_time`,
`detection_rule`, `rule_description`, `observed_value`, `expected_value`, `threshold`, `unit`,
`evidence` (JSON), `recommended_action`, `source` (TELEMETRY_SCAN/SIMULATION), `simulation_id`.
Each anomaly raises exactly one alarm (ALM-000001) linked by `anomaly_id`.
Scans are idempotent (unique `fingerprint`).
