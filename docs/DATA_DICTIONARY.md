# Data Dictionary

## Identifiers

| Prefix | Example | Entity | Allocation |
|---|---|---|---|
| FAC | FAC-001 | Facility | generator order / max+1 on create |
| MODE | MODE-001 | Operating mode | fixed list |
| PUMP | PUMP-001 | Pump | generator order (train, stage) |
| TANK | TANK-001 | Tank | generator order |
| VALVE | VALVE-001 | Valve | generator order |
| PIPE | PIPE-001 | Pipe | generator order |
| SNS | SNS-001 | Sensor | generator order |
| — | 1…100000 | Telemetry row | generator sequence (sensor, time) |
| ANM | ANM-000001 | Anomaly | max+1 |
| ALM | ALM-000001 | Alarm | max+1 |
| SIM | SIM-2026-000001 | Simulation run | per-year sequence |
| GT | GT-0001 | Ground-truth label | label order (file only) |
| INJ | INJ-0001 | Injected fault event | schedule order (manifest/ground truth) |

IDs are never reused within a database (`max(sequence) + 1`).

## Sensor measurement points

| equipment_type | sensor_type | measurement_point | Quantity | Unit | Range |
|---|---|---|---|---|---|
| PUMP | FLOW | DISCHARGE | pump discharge flow (Q_up) | m³/h | 0 – 2×design (rounded to 50) |
| PUMP | PRESSURE | DISCHARGE | discharge pressure Pd | bar | 0 – 10 |
| PUMP | PRESSURE | SUCTION | suction pressure Ps | bar | 0 – 6 |
| PIPE | FLOW | OUTLET_END | delivered flow at end of transfer main (Q_down) | m³/h | as pump flow |
| PIPE | PRESSURE | OUTLET_END | delivery pressure | bar | 0 – 6 |
| TANK | LEVEL | LEVEL | tank level | % of capacity | 0 – 100 |
| VALVE (INLET) | FLOW | INLET | supply inflow | m³/h | 0 – 2×max supply |
| VALVE (INLET) | PRESSURE | INLET | supply header pressure | bar | 0 – 6 |
| VALVE (OUTLET) | FLOW | OUTLET | consumer demand flow | m³/h | 0 – 2×design |

Tags: `FT-` flow transmitter, `PT-` pressure transmitter, `LT-` level transmitter;
first digit = facility number.

## Derived telemetry values

| sensor_type | derived_value | derived_unit | Formula |
|---|---|---|---|
| LEVEL | stored volume | m3 | level/100 × capacity_m3 |
| PRESSURE | head | m | bar / 0.0981 |
| FLOW | volume per interval | m3 | m³/h × step_minutes/60 |

## Generated files (`backend/data/generated/<scale>/`)

| File | Content |
|---|---|
| operating_modes.csv, facilities.csv, pumps.csv, tanks.csv, valves.csv, pipes.csv, sensors.csv | master data |
| telemetry.csv | id, sensor_id, timestamp, value (empty = missing), derived_value, derived_unit, source |
| ground_truth.json | labels + operational events + metadata (seed, scale, step, horizon) |
| ground_truth.csv | labels (flat) |
| manifest.json | seed, scale, counts, injected events, SHA-256 per file, dataset fingerprint, model issues |
| evaluation.json | detection metrics written after the scan |

## Ground-truth label fields

| Field | Meaning |
|---|---|
| scenario_id | GT-0001… |
| facility_id, equipment_type, equipment_id | affected asset (sensor id for SENSOR_FAULT) |
| issue_type | LEAK, BLOCKAGE, PUMP_DEGRADATION, SENSOR_FAULT, TANK_OVERCAPACITY |
| sub_type | PIPE_LEAK, PIPE_RESTRICTION, HEAD_LOSS, FLATLINE/SPIKE/OUT_OF_RANGE/MISSING/BIAS, HIGH_LEVEL |
| start_timestamp, end_timestamp (+ steps) | inclusive window |
| magnitude | leak fraction, restriction %, health factor, bias fraction or peak level |
| expected_detection | true for all fault labels (operator events are listed separately with false) |
| expected_severity | from the same severity mapping the detector uses (`rules.py`), applied to the injected magnitude or true process effect |
| detection_limit_test | true for deliberately near/below-threshold faults |
| injection_rule | human-readable rule that produced the label |

## Enumerations

* Severity: LOW, MEDIUM, HIGH, CRITICAL
* Alarm status: ACTIVE → ACKNOWLEDGED → RESOLVED → CLOSED
* Anomaly category: PROCESS, SENSOR, OPERATIONAL
* Anomaly types: LEAK, BLOCKAGE, PUMP_DEGRADATION, SENSOR_FAULT, TANK_OVERCAPACITY, ABNORMAL_FLOW, ABNORMAL_PRESSURE, ABNORMAL_LEVEL, MASS_BALANCE
* Mass balance status: BALANCED, WARNING, EXCEPTION, INSUFFICIENT_DATA; classification OK, PROCESS_IMBALANCE, MEASUREMENT_FAULT
* Scenarios: NORMAL, LEAKAGE, BLOCKAGE, PUMP_DEGRADATION, SENSOR_MALFUNCTION, HIGH_DEMAND, VALVE_CLOSURE, TANK_OVERCAPACITY
