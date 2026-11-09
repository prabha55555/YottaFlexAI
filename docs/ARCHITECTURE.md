# Architecture

## Overview

```
┌──────────────────────────── Frontend (React + Vite + TS) ────────────────────────────┐
│ Pages: Dashboard · Live Monitoring · Topology (React Flow) · Alarms · Anomalies ·    │
│        Simulation Studio · Analytics · Data Validation · Facilities · Equipment      │
│ src/api/client.ts  ← the only module that talks HTTP (fetch, error parsing, exports) │
└───────────────────────────────────────┬──────────────────────────────────────────────┘
                                        │  /api/*  (Vite dev proxy → :8000)
┌───────────────────────────────────────▼──────────────────────────────────────────────┐
│ FastAPI  app/main.py                                                                 │
│  api/equipment.py   CRUD facilities, modes, pumps, tanks, valves, pipes, sensors     │
│  api/telemetry.py   history, range filter, replay snapshot, series, export           │
│  api/operations.py  topology, mass balance, anomalies, alarms, simulations           │
│  api/insights.py    dashboard, analytics, evaluation, validation, negative cases     │
├──────────────────────────────────────────────────────────────────────────────────────┤
│ Domain layer                                                                         │
│  simulation/process_model.py  plant structure derived from the pipe graph            │
│  simulation/hydraulics.py     pump curve, system curve, valves, pipes, tank volume   │
│  simulation/engine.py         time-stepping process engine (true state)              │
│  simulation/sensors.py        noise, saturation, sensor-fault injection              │
│  simulation/scenarios.py      scenario presets + parameter validation                │
│  simulation/runner.py         validate → execute → detect → balance → persist        │
│  anomaly_detection/           rules.py (thresholds, severities) · detector.py        │
│  services/mass_balance.py     facility / tank / line balances                        │
│  topology/graph.py            NetworkX graph, validation, layout                     │
│  generation/                  layout.py · faults.py · generator.py                   │
│  validation/                  integrity.py · negative_scenarios.py                   │
│  services/                    ids, references, telemetry, anomalies, alarms, eval    │
├──────────────────────────────────────────────────────────────────────────────────────┤
│ SQLAlchemy 2.0 ORM → SQLite (backend/data/yottaflex.db, PRAGMA foreign_keys=ON, WAL) │
└──────────────────────────────────────────────────────────────────────────────────────┘
```

## Key design decisions

1. **One physical model, three consumers.** The same `ProcessModel` + hydraulic
   functions are used by (a) the synthetic data generator, (b) the simulation
   studio and (c) the anomaly detector's *expected-value* calculations. The plant
   structure (pump lines, inlets, outlets) is derived by walking the pipe graph
   built from database records, so CRUD changes to equipment are reflected in
   topology, simulation and detection without code changes.
2. **Truth vs. measurement separation.** The engine produces the true process
   state; `sensors.py` derives readings (noise, range clipping, sensor faults).
   The detector only receives readings and the *known* configuration —
   never injected faults or ground truth. Ground truth is written to separate
   files and read only by `services/evaluation_service.py`.
3. **Explainable rules first.** Every anomaly stores rule id, rule description,
   observed / expected / threshold values, unit, evidence and recommended action.
4. **Immutability where it matters.** Simulation runs are append-only
   (`SIM-<year>-<seq>`), store original config, modified parameters, effective
   config, outputs, assumptions and validation errors. Failed validations are
   persisted too (needed for simulation success-rate). Alarm status changes are
   appended to `alarm_events`.
5. **Determinism.** Generation draws from `numpy.random.SeedSequence(seed)`
   child streams (master data, fault schedule, process noise, sensor noise).
   Same seed + scale ⇒ byte-identical exports (SHA-256 in `manifest.json`).
   Simulations hash their full input (`input_hash`); identical inputs give
   identical outputs (verified by tests).
6. **Polymorphic references.** Pipe end-points and sensor mount points may
   reference pumps, tanks, valves (and pipes for sensors). SQLite cannot express
   such a foreign key, so `services/references.py` enforces it on every write and
   `validation/integrity.py` re-checks the whole database.

## Data flow

```
generate_data ──► master data ──► ProcessModel ──► engine (true state + faults)
                                                     │
                                                     ├─► sensors ──► telemetry (DB, CSV)
                                                     └─► ground_truth.json / .csv (files only)
POST /anomalies/scan ──► load telemetry ──► Detector ──► anomalies + alarms (DB)
GET  /evaluation/metrics ──► anomalies (DB) vs ground_truth.json ──► TP/FP/TN/FN
POST /simulations ──► validate ──► engine ──► sensors ──► Detector ──► mass balance
                                    └──────────► simulation_runs + anomalies + alarms
```

## Frontend structure

| Path | Purpose |
|---|---|
| `src/api/client.ts` | Fetch wrapper, query strings, error normalisation (422 `errors[]`), downloads |
| `src/api/types.ts` | Types mirroring backend schemas |
| `src/components/hooks.tsx` | `useApi` (loading/error/reload), toasts, facility scope context |
| `src/components/ui.tsx` | Cards, stats, severity badge (icon + label), pills, modal, pagination, async states |
| `src/components/charts.tsx` | Chart conventions: fixed categorical palette order, status colours, axes, tooltip |
| `src/components/Layout.tsx` | Sidebar navigation, facility selector, open-alarm counter, "Simulated data" badge |
| `src/pages/*` | One file per page |
