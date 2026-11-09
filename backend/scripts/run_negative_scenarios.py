"""Run the deliberate negative scenarios and print why each validation failed.

Usage (from backend/):  python -m scripts.run_negative_scenarios
"""
from __future__ import annotations

import json
import sys

from app.config import DATA_DIR
from app.validation.negative_scenarios import run_all


def main() -> int:
    result = run_all()
    for c in result["cases"]:
        mark = "CAUGHT" if c["detected_as_expected"] else "MISSED"
        print(f"[{mark}] {c['case_id']} {c['title']}  -> validation {c['validation_status']}")
        for e in c["errors"]:
            print(f"     - {e['code']}: {e['message']}")
    print(f"\n{result['caught']}/{result['total']} negative scenarios detected as expected.")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "negative_scenarios_report.json").write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    return 0 if result["caught"] == result["total"] else 1


if __name__ == "__main__":
    sys.exit(main())
