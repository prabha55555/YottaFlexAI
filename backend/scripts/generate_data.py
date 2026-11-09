"""Generate the synthetic dataset, load it into SQLite, run detection and evaluation.

Usage (from backend/):
    python -m scripts.generate_data --seed 20261022 --scale starter
    python -m scripts.generate_data --seed 20261022 --scale full
Options:
    --no-db       only write CSV/JSON exports (no database reset)
    --no-detect   skip the anomaly scan and evaluation
    --out DIR     export directory (default data/generated/<scale>)
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from app.config import DEFAULT_SEED, GENERATED_DIR
from app.database import SessionLocal, engine, reset_db
from app.generation.generator import SCALES, export_files, generate_dataset, persist_to_db
from app.services.anomaly_service import scan_all
from app.services.evaluation_service import ACTIVE_DATASET_FILE, evaluate


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    ap.add_argument("--scale", choices=sorted(SCALES), default="starter")
    ap.add_argument("--no-db", action="store_true")
    ap.add_argument("--no-detect", action="store_true")
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args(argv)

    t0 = time.perf_counter()
    print(f"[1/5] Generating dataset seed={args.seed} scale={args.scale} ...")
    ds = generate_dataset(args.seed, args.scale)
    print(f"      telemetry records: {len(ds.telemetry_rows):,}  ground-truth labels: {len(ds.ground_truth['labels'])}")

    print("[2/5] Writing CSV/JSON exports ...")
    manifest = export_files(ds, args.out)
    out_dir = args.out or GENERATED_DIR / args.scale
    print(f"      {out_dir}  fingerprint={manifest['dataset_fingerprint'][:16]}")

    if args.no_db:
        print("Done (exports only).")
        return 0

    print("[3/5] Resetting database and loading records ...")
    reset_db(engine)
    with SessionLocal() as db:
        persist_to_db(db, ds)
    ACTIVE_DATASET_FILE.parent.mkdir(parents=True, exist_ok=True)
    ACTIVE_DATASET_FILE.write_text(json.dumps({"seed": args.seed, "scale": args.scale,
                                               "fingerprint": manifest["dataset_fingerprint"],
                                               "counts": manifest["counts"]}, indent=2), encoding="utf-8")

    if args.no_detect:
        print(f"Done in {time.perf_counter() - t0:.1f}s (detection skipped).")
        return 0

    print("[4/5] Running rule-based anomaly detection over stored telemetry ...")
    with SessionLocal() as db:
        scan = scan_all(db)
        for fac, info in scan.items():
            print(f"      {fac}: {info['detected']} anomalies")
        print("[5/5] Evaluating detections against ground truth ...")
        ev = evaluate(db)
    (out_dir / "evaluation.json").write_text(json.dumps(ev, indent=2, default=str), encoding="utf-8")
    o = ev["overall"]
    print(f"      overall TP={o['tp']} FP={o['fp']} TN={o['tn']} FN={o['fn']} "
          f"precision={o['precision']} recall={o['recall']} F1={o['f1_score']}")
    for t, m in ev["per_type"].items():
        print(f"      {t:<18} TP={m['tp']:<4} FP={m['fp']:<4} FN={m['fn']:<4} P={m['precision']} R={m['recall']} "
              f"F1={m['f1_score']}")
    print(f"Done in {time.perf_counter() - t0:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
