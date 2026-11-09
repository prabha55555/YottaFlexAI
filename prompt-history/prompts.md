# Prompt History

**Tool:** Claude Code (Anthropic, model Claude Opus 5.5) inside VS Code, with its built-in
sub-agents for parallel frontend work.
**Format:** each prompt is recorded as an engineering request — goal, scope, constraints and
acceptance criteria — condensed from the original wording for readability. The intent, scope and
order of the prompts are unchanged; nothing was added that was not asked. Short continuation
prompts ("continue" after an interrupted session) are noted where they occurred.
No secrets, credentials or confidential data were included in any prompt.

See [docs/AI_USAGE.md](../docs/AI_USAGE.md) for how the output of these prompts was reviewed and
validated, and [docs/DEVELOPMENT_LOG.md](../docs/DEVELOPMENT_LOG.md) for the timeline.

---

## P1 — Build the application from the assignment brief

**Goal:** design, implement, test and document a complete industrial process monitoring and
simulation application in an empty workspace — working software, not a proposal.

**Stack constraints:** React + Vite + TypeScript + Tailwind + Recharts + React Flow + Lucide;
Python + FastAPI + SQLAlchemy + Pydantic; SQLite; NumPy / Pandas / NetworkX. Free, local, no paid APIs.

**Scope requested:**

| Area | Requirements |
|---|---|
| Domain model | Facility, Pump, Tank, Valve, Pipe, Sensor, Telemetry, OperatingMode, Alarm, SimulationRun with PKs, FKs, constraints, indexes; deterministic IDs (`FAC-001`, `PUMP-001`, `TANK-001`, `VALVE-001`, `PIPE-001`, `SNS-001`, `SIM-2026-000001`); CRUD APIs with proper schemas and status codes |
| Synthetic data | Seed `20261022`; 3 facilities, 20 pumps, 30 tanks, 60 valves, valid pipes, sensors, **100,000 telemetry records**; parents before children; derived values; separate ground-truth labels; `starter` and `full` scales via `python -m scripts.generate_data`; identical output for identical seed |
| Topology | NetworkX graph from DB records: nodes, directed pipes, connection validation, components, invalid connections, reachability; per-facility API |
| Engineering logic | Pump curve `H(Q) = H0 − kQ²` with degradation; tank `V(t+1) = V(t) + (Qin − Qout − Qleak)·Δt` with correct units; valves affect flow; pipe capacity, restriction and pressure limits; document simplifications honestly |
| Telemetry | Flow, pressure, level with noise and physically consistent behaviour (valve closure, blockage, leak, degradation, tank response); history and time-range queries |
| Mass balance | Inflow, outflow, storage change, leakage, balance error, status, configurable tolerance, exceptions; separate process imbalance from measurement faults |
| Detection | Explainable rules for leak, blockage, pump degradation, sensor faults (range, spike, flatline, missing, inconsistent); each anomaly carries ID, facility, equipment, type, severity, timestamp, rule, observed / expected / threshold, recommended action; **ground truth never used as input** |
| Simulation | Configurable speed, availability, valve opening, initial level, demand, restrictions, mode; 8 scenarios; capture original + modified config, validate, run, detect, alarm, persist, record assumptions; never overwrite runs; baseline comparison |
| Alarms | ACTIVE → ACKNOWLEDGED → RESOLVED → CLOSED; LOW–CRITICAL; filtering, history, related equipment and simulation |
| Evaluation | TP / FP / TN / FN, precision, recall, F1; PK / FK integrity, duplicates, missing %, topology validity, simulation success rate, mass-balance error; never fabricate metrics |
| Frontend | SCADA-style UI: Dashboard, Facilities, per-type Equipment CRUD, Topology (React Flow), Live Monitoring (labelled simulated), Anomalies, Simulation Studio, Alarms, Analytics, Data Validation — all values from the backend; loading / empty / error states, notifications, validation, pagination, filtering, no dead buttons |
| Negative cases | Pipe to missing node; tank over capacity; flow conservation violated; simulation without input config; sensor fault mislabelled as process fault — detected and explained, kept separate from baseline data |
| Quality | pytest coverage of relationships, IDs, generation, topology, physics, detection, reproducibility, alarms, evaluation; manual frontend check |
| Docs | README, architecture, schema, data dictionary, assumptions, detection rules, API, validation summary, limitations, setup, prompt history |

**Working agreement:** inspect first, then build in 12 phases (foundation → data → topology/physics →
mass balance/detection → simulation → alarms/evaluation → frontend → integration → negative cases →
testing → docs/repo prep); run and fix after each phase; decide ambiguous points sensibly and document
them; no permission stops between phases.

**Acceptance:** backend and frontend start; both datasets generate; relationships, topology,
scenarios, alarms, metrics, tests, pages and CSV/JSON exports verified; README and prompt history
complete; no secrets; repository ready to publish.

*Continuations:* the build ran across interrupted sessions; two short "continue" prompts resumed it
without changing scope.

---

## P2 — Verify end-to-end and provide start-up commands

**Goal:** confirm that everything works correctly and give exact commands to start the application.

**Acceptance:** clean restart of both servers using the documented commands; automated tests,
type-check and production build pass; every API endpoint and every page verified; commands that
work in Windows PowerShell without venv activation.

---

## P3 — Prepare the repository for submission

**Goal:** align the repository with the recruitment submission guidelines — (1) runnable with clear
install / run / verify steps, (2) public repo with understandable evolution and meaningful commits,
(3) transparent LLM use with prompt history and an account of what was reviewed and validated,
(4) visible reasoning: problem, assumptions, decisions, trade-offs, testing, limitations.

Follow-up questions in the same thread: *is the GitHub URL ready to submit?* — answered with a
gap list (missing prompt history, AI-usage write-up, single reasoning document, one large commit).

---

## P4 — Close the submission gaps

**Goal:** fix every gap from P3. Record the prompt history as a developer-style engineering log rather
than raw transcripts, and organise the commit history into meaningful, logically ordered commits.

**Constraints:** no backdated commit timestamps; keep the original pushed commit recoverable on a
backup branch; the force-push to GitHub is performed by the developer after review.

**Delivered:** this file, `docs/AI_USAGE.md`, `docs/DESIGN_DECISIONS.md`, `docs/DEVELOPMENT_LOG.md`,
`docs/WALKTHROUGH.md`, a reviewer smoke test (`scripts/smoke_test.py`), lint clean-up, README
verification section, and a restructured commit history.

---

## Delegated sub-agent prompts (issued by the AI assistant)

After the backend, API client, shared types, UI kit, layout and chart conventions were in place, the
ten frontend pages were split across three parallel sub-agents sharing the same project context.
Common rules for all three: use only the shared foundation; don't edit shared files or backend code
(report backend bugs instead); every value from the API; loading / empty / error states; fixed chart
palette, legends for ≥ 2 series, no dual axes; severity shown as icon + label; type-check before finishing.

| Agent | Pages | Key requirements |
|---|---|---|
| A | Dashboard, Live Monitoring, Analytics | KPI tiles, plant status, trends, tank levels; telemetry replay with play/pause and quality flags; pump performance, flow/pressure, tank utilisation, anomaly and alarm trends, detection confusion matrices, data-quality metrics |
| B | Simulation Studio, Alarms, Anomalies | Scenario + parameter editor with field-level 422 errors; results, charts, baseline and two-run comparison, exports, history, deep links; alarm lifecycle actions with history and bulk acknowledge; anomaly filters, detail, on-demand scan, exports |
| C | Facilities, Equipment, Topology, Validation | Facility CRUD with summaries; one config-driven CRUD page for five equipment types; React Flow topology with health colouring and click-through details; validation report and negative-case cards |

Reports from the agents flagged two backend issues (duplicate-name check counted across facilities;
dead code in topology sensor health); both were fixed. When a session was interrupted, each agent was
resumed with a short "continue from the existing files" instruction.
