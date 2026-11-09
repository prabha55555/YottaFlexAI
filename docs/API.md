# API Reference

Base URL `http://localhost:8000/api`. Interactive OpenAPI docs: `http://localhost:8000/docs`.
All list endpoints that return pages use `{items, total, skip, limit}`.

## Errors

| Status | When | Body |
|---|---|---|
| 404 | resource not found | `{"detail": "PUMP PUMP-999 not found"}` |
| 409 | duplicate, in-use delete, invalid alarm transition | `{"detail": {"error": "IN_USE", "message": "..."}}` |
| 422 | schema / reference / range validation | `{"detail": {"error": "MISSING_NODE", "message": "...", "errors": [{"field", "message"}]}}` |

## System
| Method | Path | Description |
|---|---|---|
| GET | `/health` | DB status, counts, active dataset (seed, scale, fingerprint) |

## Master data & equipment
| Method | Path | Query / body |
|---|---|---|
| GET | `/facilities` | — |
| POST | `/facilities` | `{name, location, description, status, operating_mode_id}` → 201 |
| GET/PUT/DELETE | `/facilities/{id}` | DELETE refuses non-empty facility unless `force=true` |
| GET | `/facilities/{id}/summary` | counts, telemetry rows, open alarms, storage, installed flow |
| GET/POST | `/operating-modes` | |
| GET | `/pumps`, `/tanks`, `/valves`, `/pipes`, `/sensors` | `facility_id, q (search), filter (status/role/sensor_type), skip, limit` |
| POST | same | create (ID allocated server-side) → 201 |
| GET/PUT/DELETE | `/{kind}/{id}` | DELETE → 409 if referenced by pipes/sensors |

Pipe and sensor writes are validated for existing end-points/equipment, same facility,
no self-loops, no duplicate connections and valid sensor placement.

## Telemetry (simulated)
| Method | Path | Query |
|---|---|---|
| GET | `/telemetry` | `facility_id, sensor_id, sensor_type, start, end, skip, limit` (422 if start > end) |
| GET | `/telemetry/range` | `facility_id` → start, end, record count |
| GET | `/telemetry/series` | `facility_id, sensor_ids (csv) or sensor_type, start, end, max_points` (bucket-averaged) |
| GET | `/telemetry/snapshot` | `facility_id, at` → all readings at the replay cursor with quality GOOD/SUSPECT/BAD |
| GET | `/telemetry/export` | same filters + `format=csv|json` |

## Topology & mass balance
| Method | Path | Query |
|---|---|---|
| GET | `/topology/{facility_id}` | `include_simulation_alarms` → nodes (with layout, health, alarms, sensors), edges, validation (issues, components, reachability, paths) |
| GET | `/mass-balance` | `facility_id, start, end, tolerance_pct (default 2), window_hours` |

## Anomalies
| Method | Path | Query |
|---|---|---|
| GET | `/anomalies` | `facility_id, anomaly_type, severity, category, source, simulation_id, equipment_id, start, end, skip, limit` |
| GET | `/anomalies/stats` | counts by type, severity, category, rule, facility |
| GET | `/anomalies/{id}` | |
| POST | `/anomalies/scan` | `facility_id?, tolerance_pct?` — run detection over stored telemetry (idempotent) |
| GET | `/anomalies/export` | `format=csv|json` + filters |

## Alarms
| Method | Path | Query / body |
|---|---|---|
| GET | `/alarms` | `status (csv), severity (csv), facility_id, equipment_id, simulation_id, source=LIVE|SIMULATION, alarm_type, skip, limit` |
| GET | `/alarms/stats` | by status, open by severity |
| GET | `/alarms/{id}` | detail + history events + linked anomaly |
| POST | `/alarms/{id}/acknowledge` · `/resolve` · `/close` | `{actor, note}`; 409 on invalid transition |
| GET | `/alarms/export` | `format=csv|json` |

## Simulations
| Method | Path | Notes |
|---|---|---|
| GET | `/simulations/scenarios` | `facility_id` → scenarios with resolved preset parameters |
| POST | `/simulations` | body below → 201 run detail; 422 with `simulation_id` + field errors (run stored as FAILED) |
| GET | `/simulations` | `facility_id, scenario, status, skip, limit` |
| GET | `/simulations/{id}` | full detail (configs, KPIs, mass balance, time series, assumptions) |
| GET | `/simulations/compare` | `baseline_id, modified_id` → KPI deltas, per-line/tank values, overlay time series |
| GET | `/simulations/{id}/export` | `format=json` (full incl. readings & anomalies) or `format=csv&content=timeseries|readings` |

```json
POST /api/simulations
{
  "facility_id": "FAC-001",
  "scenario": "LEAKAGE",
  "name": "Leak on train A",
  "seed": 20261022, "steps": 96, "step_minutes": 15, "fault_start_step": 24,
  "apply_preset": true, "run_baseline": true,
  "parameters": {
    "operating_mode_id": "MODE-002", "demand_factor": 1.0,
    "pump_speeds": {"PUMP-001": 95}, "pump_availability": {"PUMP-002": true},
    "valve_openings": {"VALVE-004": 60}, "tank_initial_levels": {"TANK-004": 70},
    "flow_demand": {"VALVE-007": 120}, "pipe_restrictions": {"PIPE-005": 50},
    "pipe_leaks": {"PIPE-005": 0.15}, "pump_health": {"PUMP-001": 0.8},
    "sensor_faults": {"SNS-005": "BIAS"}
  }
}
```

## Dashboard, analytics, evaluation, validation
| Method | Path | Description |
|---|---|---|
| GET | `/dashboard/summary` | `facility_id?` totals, equipment health, plant status, trends, tank levels, recent simulations |
| GET | `/analytics/overview` | `facility_id` pump performance index, flow/pressure analysis, tank utilisation, anomaly distribution, alarm trend, simulation performance |
| GET | `/evaluation/metrics` | TP/FP/TN/FN, precision, recall, F1 per issue type + event-level recall, latency, severity agreement |
| GET | `/evaluation/ground-truth` | the active dataset's ground-truth file |
| GET | `/evaluation/data-quality` | PK/FK integrity, duplicates, missing %, topology validity, simulation success rate, mass-balance error |
| GET | `/validation/report` | full integrity report (PK, FK, duplicates, missing, topology, tank capacity, mass balance failures, invalid readings, simulation errors) |
| GET | `/validation/negative-scenarios` | runs the five negative fixtures and explains each failure |
