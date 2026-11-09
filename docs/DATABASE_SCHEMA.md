# Database Schema

SQLite (`backend/data/yottaflex.db`), SQLAlchemy 2.0 models in `backend/app/models/`.
`PRAGMA foreign_keys=ON` and WAL journaling are set on every connection.

```
operating_modes 1───* facilities 1───* pumps
                                 1───* tanks
                                 1───* valves
                                 1───* pipes  (from_node_id / to_node_id → pumps|tanks|valves  *service-enforced*)
                                 1───* sensors (equipment_id → pumps|tanks|valves|pipes  *service-enforced*)
sensors 1───* telemetry
facilities 1───* simulation_runs ──(baseline_simulation_id)──► simulation_runs
facilities 1───* anomalies *───1 simulation_runs (nullable)
anomalies 1───1 alarms *───1 simulation_runs (nullable)
alarms 1───* alarm_events
```

## Tables

### operating_modes
| Column | Type | Constraints |
|---|---|---|
| id | VARCHAR(20) | PK, `MODE-001` |
| name | VARCHAR(50) | UNIQUE, NOT NULL |
| description | TEXT | |
| demand_factor | FLOAT | CHECK 0 ≤ x ≤ 3 |
| pump_speed_factor | FLOAT | CHECK 0 < x ≤ 1.2 |

### facilities
| Column | Type | Constraints |
|---|---|---|
| id | VARCHAR(20) | PK, `FAC-001` |
| name | VARCHAR(120) | UNIQUE, NOT NULL |
| location, description | VARCHAR / TEXT | |
| status | VARCHAR(20) | CHECK IN (OPERATIONAL, MAINTENANCE, SHUTDOWN) |
| operating_mode_id | VARCHAR(20) | FK → operating_modes.id ON DELETE SET NULL |
| created_at | DATETIME | |

### pumps
| Column | Type | Constraints |
|---|---|---|
| id | VARCHAR(20) | PK, `PUMP-001` |
| facility_id | VARCHAR(20) | FK → facilities.id ON DELETE CASCADE, INDEX |
| name | VARCHAR(120) | NOT NULL |
| rated_flow_m3h | FLOAT | CHECK > 0 |
| shutoff_head_m (H0) | FLOAT | CHECK > 0 |
| curve_k | FLOAT | CHECK > 0, m/(m³/h)² |
| speed_pct | FLOAT | CHECK 0–110 |
| rated_power_kw | FLOAT | |
| best_efficiency | FLOAT | CHECK 0 < x ≤ 1 |
| health_factor | FLOAT | CHECK 0 < x ≤ 1 |
| available | BOOLEAN | |
| status | VARCHAR(20) | CHECK IN (RUNNING, STOPPED, MAINTENANCE, TRIPPED) |

### tanks
| Column | Type | Constraints |
|---|---|---|
| id | VARCHAR(20) | PK, `TANK-001` |
| facility_id | VARCHAR(20) | FK, INDEX |
| capacity_m3, height_m | FLOAT | CHECK > 0 |
| elevation_m | FLOAT | base elevation above pump datum |
| initial_level_pct, setpoint_pct | FLOAT | CHECK 0–100 |
| high_alarm_pct, low_alarm_pct | FLOAT | CHECK low < high ≤ 100 |
| status | VARCHAR(20) | CHECK IN (IN_SERVICE, OUT_OF_SERVICE) |

### valves
| Column | Type | Constraints |
|---|---|---|
| id | VARCHAR(20) | PK, `VALVE-001` |
| facility_id | VARCHAR(20) | FK, INDEX |
| valve_type | VARCHAR(20) | CHECK IN (GATE, GLOBE, BUTTERFLY, BALL, CONTROL, CHECK) |
| role | VARCHAR(20) | CHECK IN (INLINE, INLET, OUTLET) |
| opening_pct | FLOAT | CHECK 0–100 |
| resistance_full_open | FLOAT | CHECK > 0 |
| boundary_flow_m3h | FLOAT NULL | max supply (INLET) / nominal demand (OUTLET) |
| status | VARCHAR(20) | |

### pipes
| Column | Type | Constraints |
|---|---|---|
| id | VARCHAR(20) | PK, `PIPE-001` |
| facility_id | VARCHAR(20) | FK, INDEX |
| from_node_type / to_node_type | VARCHAR(10) | CHECK IN (PUMP, TANK, VALVE) |
| from_node_id / to_node_id | VARCHAR(20) | INDEX; existence + same facility enforced by `services/references.py` |
| length_m, diameter_mm | FLOAT | CHECK > 0 |
| friction_factor | FLOAT | |
| max_flow_m3h, max_pressure_bar | FLOAT | CHECK > 0 |
| restriction_pct | FLOAT | CHECK 0 ≤ x < 100 |
| status | VARCHAR(20) | |
| — | | UNIQUE(from_node_id, to_node_id); CHECK from_node_id ≠ to_node_id |

### sensors
| Column | Type | Constraints |
|---|---|---|
| id | VARCHAR(20) | PK, `SNS-001` |
| facility_id | VARCHAR(20) | FK, INDEX |
| tag | VARCHAR(40) | UNIQUE(facility_id, tag), e.g. `FT-101` |
| equipment_type | VARCHAR(10) | CHECK IN (PUMP, TANK, VALVE, PIPE) |
| equipment_id | VARCHAR(20) | INDEX(equipment_type, equipment_id); service-enforced |
| sensor_type | VARCHAR(10) | CHECK IN (FLOW, PRESSURE, LEVEL) |
| measurement_point | VARCHAR(20) | DISCHARGE, SUCTION, OUTLET_END, LEVEL, INLET, OUTLET |
| unit | VARCHAR(10) | m3/h, bar, % |
| min_range, max_range | FLOAT | CHECK min < max |
| accuracy_pct | FLOAT | |
| status | VARCHAR(20) | CHECK IN (ACTIVE, INACTIVE, FAULTY) |

### telemetry
| Column | Type | Constraints |
|---|---|---|
| id | INTEGER | PK (deterministic sequence from generator) |
| sensor_id | VARCHAR(20) | FK → sensors.id ON DELETE CASCADE |
| timestamp | DATETIME | INDEX; UNIQUE(sensor_id, timestamp) |
| value | FLOAT NULL | NULL = missing reading |
| derived_value | FLOAT NULL | LEVEL→volume m³, PRESSURE→head m, FLOW→m³ per interval |
| derived_unit | VARCHAR(10) | |
| source | VARCHAR(20) | `SYNTHETIC` |

### simulation_runs
| Column | Type | Notes |
|---|---|---|
| id | VARCHAR(24) | PK, `SIM-2026-000001` |
| facility_id | FK | |
| name, scenario | | |
| status | | CHECK IN (COMPLETED, FAILED) |
| seed, steps, step_minutes, start_time | | CHECK steps > 0, step_minutes > 0 |
| baseline_simulation_id | FK → simulation_runs.id | |
| original_config | JSON | equipment snapshot at run time |
| modified_parameters | JSON | `{user, resolved, fault_start_step}` |
| effective_config | JSON | operating settings + injected faults + what the detector knew |
| input_hash | VARCHAR(64) | SHA-256 of canonical inputs |
| summary, mass_balance, timeseries, readings | JSON | outputs |
| assumptions, validation_errors | JSON | |
| duration_ms, created_at | | |

### anomalies
| Column | Type | Notes |
|---|---|---|
| id | VARCHAR(24) | PK, `ANM-000001` |
| fingerprint | VARCHAR(64) | UNIQUE (idempotent scans) |
| facility_id | FK | INDEX |
| equipment_type, equipment_id, sensor_id | | |
| anomaly_type | | INDEX(facility_id, anomaly_type) |
| category | | CHECK IN (PROCESS, SENSOR, OPERATIONAL) |
| severity | | CHECK IN (LOW, MEDIUM, HIGH, CRITICAL) |
| detection_rule, rule_description | | |
| start_time, end_time, detected_at | DATETIME | |
| observed_value, expected_value, threshold, unit | | |
| evidence | JSON | |
| recommended_action | TEXT | |
| source | | TELEMETRY_SCAN / SIMULATION |
| simulation_id | FK → simulation_runs (CASCADE) | |

### alarms
| Column | Type | Notes |
|---|---|---|
| id | VARCHAR(24) | PK, `ALM-000001` |
| facility_id, equipment_type, equipment_id | | |
| anomaly_id | FK → anomalies (UNIQUE) | one alarm per anomaly |
| simulation_id | FK → simulation_runs | |
| alarm_type, severity | | CHECK severity |
| status | | CHECK IN (ACTIVE, ACKNOWLEDGED, RESOLVED, CLOSED), INDEX |
| message, recommended_action | | |
| raised_at, acknowledged_at/by, resolved_at/by, closed_at/by | | |

### alarm_events (history)
| Column | Type | Notes |
|---|---|---|
| id | INTEGER | PK |
| alarm_id | FK → alarms (CASCADE) | INDEX |
| from_status, to_status | | |
| actor, note, timestamp | | append-only |

Ground-truth labels are **not** stored in the database; they live in
`backend/data/generated/<scale>/ground_truth.json|csv`.
