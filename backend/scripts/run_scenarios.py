"""Execute every simulation scenario for every facility (with linked NORMAL baselines)
and print what each run detected.

Usage (from backend/):  python -m scripts.run_scenarios [--steps 96] [--facility FAC-001]
"""
from __future__ import annotations

import argparse
import json
import sys

from sqlalchemy import select

from app.config import DATA_DIR
from app.database import SessionLocal, init_db
from app.models import Alarm, Facility
from app.simulation.runner import SimulationValidationError, run_simulation
from app.simulation.scenarios import SCENARIOS

EXPECTED = {
    "LEAKAGE": "LEAK", "BLOCKAGE": "BLOCKAGE", "PUMP_DEGRADATION": "PUMP_DEGRADATION",
    "SENSOR_MALFUNCTION": "SENSOR_FAULT", "VALVE_CLOSURE": "ABNORMAL_FLOW", "TANK_OVERCAPACITY": "TANK_OVERCAPACITY",
    "HIGH_DEMAND": None, "NORMAL": None,
}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--steps", type=int, default=96)
    ap.add_argument("--facility", default=None)
    args = ap.parse_args(argv)
    init_db()
    rows, ok = [], True
    with SessionLocal() as db:
        facs = [args.facility] if args.facility else db.scalars(select(Facility.id).order_by(Facility.id)).all()
        for fac in facs:
            for sc in SCENARIOS:
                try:
                    run = run_simulation(db, fac, sc, {}, steps=args.steps, run_baseline=sc != "NORMAL",
                                         name=f"{sc.title()} scenario check")
                except SimulationValidationError as exc:
                    print(f"{fac} {sc:<20} FAILED validation: {exc.run.validation_errors}")
                    ok = False
                    continue
                k = run.summary["kpis"]
                types = run.summary["anomalies_by_type"]
                alarms = db.query(Alarm).filter(Alarm.simulation_id == run.id).count()
                exp = EXPECTED[sc]
                hit = exp is None or types.get(exp, 0) > 0
                ok &= hit
                rows.append({"facility": fac, "scenario": sc, "simulation_id": run.id,
                             "baseline_id": run.baseline_simulation_id, "anomalies": types, "alarms": alarms,
                             "expected_type": exp, "expected_detected": hit, "kpis": k})
                print(f"{fac} {sc:<20} {run.id}  alarms={alarms:<3} served={k['demand_served_pct']}%  "
                      f"leak={k['true_leak_m3']}m3 overflow={k['overflow_m3']}m3  balance={k['mass_balance_status']}"
                      f"  anomalies={json.dumps(types)}  {'OK' if hit else 'MISSING ' + str(exp)}")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "scenario_runs.json").write_text(json.dumps(rows, indent=2, default=str), encoding="utf-8")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
