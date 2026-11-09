"""Print detection metrics and data-quality metrics for the database contents.

Usage (from backend/):  python -m scripts.run_evaluation
"""
from __future__ import annotations

import json
import sys

from app.config import DATA_DIR
from app.database import SessionLocal
from app.services.evaluation_service import evaluate
from app.validation import integrity


def main() -> int:
    with SessionLocal() as db:
        ev = evaluate(db)
        if not ev.get("available"):
            print(ev["message"])
            return 1
        report = {
            "detection": ev,
            "primary_keys": integrity.primary_key_checks(db),
            "foreign_keys": integrity.foreign_key_checks(db),
            "duplicates": integrity.duplicate_checks(db),
            "missing_values": integrity.missing_value_checks(db),
            "topology": {k: v for k, v in integrity.topology_checks(db).items()},
            "simulations": integrity.simulation_checks(db),
            "mass_balance": integrity.mass_balance_checks(db),
        }
    o = ev["overall"]
    print(f"Detection (window={ev['window_hours']}h, units={o['tp'] + o['fp'] + o['tn'] + o['fn']}):")
    print(f"  TP={o['tp']} FP={o['fp']} TN={o['tn']} FN={o['fn']}  P={o['precision']} R={o['recall']} F1={o['f1_score']}")
    for t, m in ev["per_type"].items():
        el = ev["event_level"][t]
        print(f"  {t:<18} P={m['precision']} R={m['recall']} F1={m['f1_score']}  events {el['detected']}/{el['labels']} "
              f"latency={el['mean_latency_min']}min severity_agreement={el['severity_agreement']}")
    print(f"PK errors={report['primary_keys']['error_count']}  FK errors={report['foreign_keys']['error_count']}  "
          f"duplicates={report['duplicates']['total']}  missing={report['missing_values']['telemetry_missing_pct']}%")
    print(f"Topology valid: {report['topology']['valid_facilities']}/{report['topology']['total']}  "
          f"Simulation success: {report['simulations']['success_rate_pct']}%  "
          f"Mass balance mean |error|: {report['mass_balance']['mean_abs_balance_error_pct']}%")
    (DATA_DIR / "evaluation_report.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(f"Report written to {DATA_DIR / 'evaluation_report.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
