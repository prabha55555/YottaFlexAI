# Design Decisions, Assumptions and Trade-offs

## 1. The problem

Operators of a water/process plant need to know, from instrument data alone, **whether something is
physically wrong** (a leak, a blockage, a worn pump, a tank about to overflow) **or whether an
instrument is lying** — and to test "what if" changes before making them. The core difficulty is
that the same symptom (e.g. "less flow arrives than left") can be either a process fault or a
measurement fault, and treating one as the other sends a crew to the wrong place.

So the system has to: model the plant credibly, generate data with known faults, detect faults with
explainable rules, separate process faults from sensor faults, and prove how well it does that
against labels it never sees.

## 2. Assumptions

| Assumption | Why it is reasonable | Where it matters |
|---|---|---|
| Fluid is water, incompressible, ρ = 1000 kg/m³ | Typical of treatment/transfer plants; allows volume balance = mass balance | Mass balance, pressures |
| Quasi-steady hydraulics per 15-min step | Pump/valve transients settle in seconds; 15-min telemetry cannot see them | Whole simulation |
| Plant = independent process trains (tank → pump → tank) | Common layout; makes every pump's operating point solvable in closed form | Topology, simulation |
| Head tanks fed by a level-controlled external supply; end tanks feed consumer demand with a daily profile | Matches how utility-fed plants behave; keeps the dataset stable for 6.5 days | Data realism |
| Operator setpoints (speeds, valve positions, demand mode) are known to the monitoring system; faults are not | That is the real information split in a SCADA system | Detection fairness |
| Sensor error = accuracy-based Gaussian noise, range saturation, low-flow cut-off | Standard transmitter behaviour | False-positive rate |
| All telemetry is simulated | The brief requires it; the UI labels it everywhere | Honesty of results |

Ambiguities in the brief and how they were resolved are recorded alongside each decision below.

## 3. Key decisions

### D1 — One physical model shared by generator, simulator and detector
**Decision:** a single `ProcessModel` + hydraulics module is used to generate the dataset, to run
studio simulations, and to compute the detector's *expected* values.
**Alternatives:** independent random telemetry; separate simulator and detector models.
**Trade-off:** physical consistency (closing a valve really lowers downstream flow and raises pump
pressure) at the cost of a coupled design. Risk mitigated by giving the detector only *readings plus
known setpoints* — never the injected faults — so shared physics does not leak the answer.

### D2 — Closed-form operating point instead of a network solver
**Decision:** each pump line is solved analytically: `hf·s²·H0 − hf·k·Q² = Hs + R·Q²`.
**Alternatives:** Hardy-Cross / Newton network solver, EPANET.
**Trade-off:** instant, deterministic and explainable, but no looped or branched networks. Documented
as a limitation; unsupported structures are still shown in the topology and reported as model issues.

### D3 — Exactly 100,000 telemetry rows
**Decision:** 160 sensors × 625 fifteen-minute steps. Missing readings are stored as rows with a
`NULL` value (a historian "no data" record) rather than omitted.
**Trade-off:** hits the required count exactly and keeps missing data detectable; a sparse-ingestion
path (absent timestamps) is also handled by re-gridding on load.

### D4 — Polymorphic references enforced in the service layer
**Decision:** a pipe can connect a pump, tank or valve; SQLite cannot express that as one foreign
key. Every write is checked by `services/references.py`, and `validation/integrity.py` re-checks
the whole database.
**Alternatives:** a generic "equipment" super-table.
**Trade-off:** simpler schema and clearer API errors (`MISSING_NODE`, `CROSS_FACILITY_CONNECTION`)
versus relying on application code instead of the database for that one relationship.

### D5 — Rules first, with a three-way reconciliation for leaks
**Decision:** transparent threshold rules with persistence. A flow imbalance is classified by
comparing three measurements: pump flow meter, delivery flow meter and the receiving tank's level
change. Whichever meter the tank agrees with is trusted.
**Alternatives:** ML anomaly scores; a naive "imbalance ⇒ leak" rule.
**Trade-off:** fully explainable (observed / expected / threshold / evidence on every anomaly) and
correctly separates a 12.7 % meter bias from a real leak; but thresholds must be tuned per plant.

### D6 — Model-based expectations use *measured* tank levels
**Decision:** expected pump flow and pressure are computed from the pump curve, the known setpoints
and the current measured levels.
**Why:** the expectation then tracks normal operating changes (levels, demand), so only genuine
deviations fire. This is what separates a blockage (flow ↓, pressure ↑) from pump wear (flow ↓,
head ↓ below its curve).

### D7 — Window-based evaluation with real true negatives
**Decision:** unit = (issue type, asset, 6-hour window); 6,750 units on the full dataset.
**Alternatives:** event-only matching (no true negatives) or per-sample scoring.
**Trade-off:** gives an honest TN count and comparable precision/recall; window size affects
accuracy, so event-level recall, latency and severity agreement are reported too.

### D8 — Deliberately undetectable faults in the dataset
**Decision:** the full dataset includes faults just below the thresholds (3.5 % leak, 7 % head loss,
4 % meter bias) and one just above (6 % leak).
**Why:** the first evaluation scored a perfect 1.0, which shows nothing about limits. With
detection-limit tests, recall is 0.85 and the misses are exactly the predicted ones — evidence that
the thresholds behave as documented.

### D9 — Immutable simulation runs, failures included
**Decision:** every run gets a new `SIM-<year>-<seq>` ID and stores original configuration,
user + resolved parameters, effective configuration, outputs, assumptions and an input hash.
Invalid inputs are stored as `FAILED` runs with field-level errors.
**Why:** traceability and reproducibility (same input hash ⇒ same outputs, tested), and a meaningful
simulation success-rate metric.

### D10 — One alarm per anomaly, strict lifecycle, append-only history
**Decision:** ACTIVE → ACKNOWLEDGED → RESOLVED → CLOSED with 409 on skipped steps; every change is an
`alarm_events` row. Re-scanning telemetry is idempotent (anomaly fingerprints).
**Trade-off:** simple and auditable; no alarm shelving/suppression grouping (out of scope).

### D11 — "Live" monitoring as a replay
**Decision:** the monitoring page replays stored telemetry with a time cursor and play/pause,
labelled "Simulated telemetry replay — no hardware connected".
**Why:** the brief forbids implying hardware connectivity; streaming infrastructure would add
complexity without adding evidence.

### D12 — Frontend data rules
**Decision:** a single API client; every number from the backend; severity always icon + label;
fixed colour order for series; route-level code splitting.
**Why:** no fake charts, accessible status colours, fast first load.

## 4. Testing approach — how we know it works

| Layer | What is checked | How |
|---|---|---|
| Physics | Pump curve, operating point, valve closure, blockage, tank integration, overflow; mass balance closes to 0 | `tests/test_physics.py` |
| Detection | Each fault type detected on simulated data; no false faults in normal operation; meter bias not called a leak; starved pump not called degraded | `tests/test_detection.py` |
| Data | Exactly 100,000 rows; ID formats; referential integrity; derived values; determinism by SHA-256 | `tests/test_data_generation.py` |
| API & workflows | CRUD rules, topology, simulation reproducibility and immutability, all scenarios, alarm lifecycle, evaluation arithmetic, negative cases, exports | `tests/test_api_and_workflows.py` |
| End to end | 77 API calls + 25 data checks against the running stack, including rejections, cleaned up afterwards | `python -m scripts.smoke_test` |
| Detection quality | Precision / recall / F1 against ground truth the detector never reads | `python -m scripts.run_evaluation` |
| Scenarios | All 8 scenarios on all 3 facilities raise their expected anomaly | `python -m scripts.run_scenarios` |
| Negative cases | 5 invalid fixtures rejected with explanations | `python -m scripts.run_negative_scenarios` |
| UI | Every page in a real browser, zero console errors, interactive flows | Manual / browser automation (see VALIDATION_SUMMARY) |

Results: [VALIDATION_SUMMARY.md](VALIDATION_SUMMARY.md). Limitations: [KNOWN_LIMITATIONS.md](KNOWN_LIMITATIONS.md).

## 5. What I would do next

1. Replace the closed-form line solver with a small network solver to support branches and loops.
2. Calibrate thresholds against real plant data and add drift detection (slow bias) using rolling
   reconciliation.
3. Move simulations to a background job queue and SQLite to PostgreSQL for multi-user use.
4. Add authentication so alarm actions are tied to real users.
