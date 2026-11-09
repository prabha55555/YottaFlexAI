# Development Log

How the solution evolved. Times are approximate local times (IST, UTC+05:30), taken from file
creation timestamps and the session log. The repository was not under version control while it was
being built; the commit history was organised afterwards into logical, reviewable steps (see the end
of this file). Commit timestamps are the real times the commits were made — nothing is backdated.

## Timeline

| When | Phase | What happened |
|---|---|---|
| 8 Nov, 00:18 | Inspection | Empty workspace confirmed; toolchain checked (Python 3.12, Node 24); venv and npm install started in parallel |
| 00:20 – 00:35 | Foundation & physics | Config, SQLAlchemy models with constraints; hydraulic functions; process model derived from the pipe graph; time-stepping engine; sensor noise and fault modes |
| 00:35 – 00:45 | Data & detection | Mass-balance engine; detector rules; master-data layout and fault injection; first full-scale run: exactly 100,000 rows, true balance closing to 0 m³, every injected fault detected, meter bias correctly classified as a sensor fault |
| 00:45 – 01:00 | Negative cases | Five invalid fixtures in `negative_cases/` and their validators — 5/5 rejected with explanations |
| 8 Nov, ~09:50 | API & scripts | Schemas, CRUD router factory, telemetry / topology / alarms / simulation / evaluation / validation endpoints; `generate_data` CLI end-to-end (generate → load → scan → evaluate) |
| ~10:00 | Honest evaluation | First evaluation scored a perfect 1.0; added near/below-threshold faults → recall 0.85 with the misses exactly where thresholds predict |
| 8 Nov, ~23:55 | Tests | pytest suite against an isolated temp DB; fixed a FastAPI bug (request bodies read as query params); moved startup to a lifespan handler — 42 tests passing |
| 9 Nov, ~00:00 – 00:10 | Frontend foundation & docs | API client, shared types, UI kit, hooks, layout, chart conventions; architecture, assumptions, rules, schema, dictionary, API, limitations docs; ten pages delegated to three parallel sub-agents |
| (interruption) | — | Session ended mid-way; each agent had finished one page; resumed with the remaining pages |
| 9 Nov, ~09:30 – 09:50 | Integration | All pages in; duplicate-name check fixed (reported by an agent); route code-splitting |
| ~09:40 – 10:00 | Verification | Fresh regeneration; 24 scenario runs; false positive found (starved pump reported as degraded) → rule fixed + regression test (43 tests); browser check of every page found charts missing axes/legends → helper fix; alarm, CRUD and export flows exercised in the UI; validation summary written from measured results |
| ~10:30 – 10:45 | Start-up verification | Clean restart with the documented commands; 102-check API smoke test; Windows PowerShell commands added to README |
| 9 Nov, 10:47 | First push | Whole project pushed as a single commit |
| 9 Nov, later | Submission prep | Lint clean-up, AI-usage disclosure, design decisions, walkthrough, smoke test script; history reorganised into the commits below |

## Commit map

The commits follow the dependency order of the system, so each one can be reviewed on its own:

1. Project scaffolding — tooling, dependencies, ignore rules
2. Domain model and database layer
3. Hydraulic model, process model and simulation engine
4. Mass balance and rule-based anomaly detection
5. Synthetic data generator with fault injection and ground truth (uses the detector's severity rules
   to label expected severities)
6. NetworkX topology and validation
7. Services: identifiers, references, telemetry, anomalies, alarms, evaluation
8. Simulation studio runner and scenarios
9. Data integrity checks and negative scenarios
10. REST API
11. CLI scripts
12. Backend test suite
13. Frontend foundation
14. Frontend operations pages
15. Frontend engineering and master-data pages
16. Technical documentation and screenshots
17. Submission documents: AI usage, prompt history, design decisions, walkthrough
