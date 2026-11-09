# Walkthrough Guide (≈ 15 minutes)

A suggested script for presenting the solution, followed by likely questions with short answers.

## Before the session
```powershell
cd backend;  .\.venv\Scripts\python.exe -m scripts.generate_data --seed 20261022 --scale full
.\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000          # terminal 1
cd frontend; npm run dev                                                  # terminal 2
```
Open http://localhost:5173 and http://localhost:8000/docs.

## Script

| Min | Show | Say |
|---|---|---|
| 0–2 | README, architecture diagram | The problem: tell process faults from instrument faults. One physical model drives data generation, simulation and the detector's expectations. |
| 2–4 | **Plant Topology** (FAC-001) | Built from DB records with NetworkX: 3 trains, flow direction, validation (components, supply→demand paths). Red nodes = active alarms. Click a pump → details and alarms. |
| 4–6 | **Live Monitoring** | Replay of 100,000 simulated readings; press Play; quality flags GOOD / SUSPECT / BAD come from the sensor-validation rules. |
| 6–8 | **Anomaly Detection** → open a LEAK and the FLOW_RECONCILIATION sensor fault | Every anomaly shows rule, observed / expected / threshold and evidence. The reconciliation compares both flow meters with the tank level change — that is how a meter bias is *not* called a leak. |
| 8–10 | **Simulation Studio** → run *Blockage*, compare with baseline | Inputs validated and stored; faults hidden from the detector; blockage = flow ↓ + pump pressure ↑; true mass-balance closure 0. Show the 422 field error by entering a 150 % valve opening. |
| 10–11 | **Alarm Management** | Acknowledge → resolve → close; illegal skips return 409; history is append-only. |
| 11–13 | **Analytics** → detection evaluation | P = 1.00, R = 0.85, F1 = 0.92 on 6,750 window units. The three misses are deliberate below-threshold faults — proof the thresholds behave as documented, not a hidden failure. |
| 13–14 | **Data Validation** → negative scenarios | Five invalid fixtures kept outside the baseline DB, each rejected with an explanation. |
| 14–15 | `pytest -q`, `scripts.smoke_test` | 43 tests; 102 end-to-end checks; deterministic data (same SHA-256 fingerprint every run). |

## Likely questions

**Is this a real hydraulic solver?** No. Each pump line's operating point is solved in closed form
(pump curve ∩ system curve) per 15-minute step. Good enough to keep flow, pressure and level
physically consistent; not for looped networks or transients. Stated in SIMULATION_ASSUMPTIONS.md.

**How do you avoid using the ground truth in detection?** The detector's signature only accepts the
plant model, known setpoints and readings (a test asserts this). Ground truth lives in files that
only the evaluation service reads.

**How do you tell a blockage from pump wear?** Blockage pushes the pump left on its curve: flow
drops and discharge pressure *rises* above expectation. Wear lowers the whole curve: measured head
at the measured flow falls below the curve. A starving pump (empty suction tank) is excluded from the
wear rule.

**Why are precision and recall so high?** The data is synthetic and the thresholds were designed for
its noise model; that is why below-threshold faults were added. On real data, thresholds would need
calibration — listed in KNOWN_LIMITATIONS.md.

**Why window-based metrics?** Without fixed units there are no true negatives. Six-hour windows per
asset and issue type give a countable negative class; event-level recall, latency and severity
agreement are reported alongside.

**What breaks first at scale?** SQLite single-writer and synchronous simulations. Next steps:
PostgreSQL, a job queue, and a network solver.

**Where did AI help, and what did you check?** See AI_USAGE.md — and be ready to describe your own
review in your words.
