"""Synthetic data generation engine.

Order of generation (parents before children):
  operating modes -> facilities -> tanks/pumps/valves -> pipes -> sensors
  -> true process simulation -> fault injection -> sensor telemetry
  -> derived values -> ground-truth labels (separate files).

Determinism: every random draw comes from ``numpy.random.SeedSequence(seed)``
child streams; identical seed + scale => byte-identical CSV exports (verified
by SHA-256 hashes in ``manifest.json``).
"""
from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np
from sqlalchemy import insert
from sqlalchemy.orm import Session

from app.config import GENERATED_DIR
from app.generation.faults import build_fault_schedule, build_ground_truth
from app.generation.layout import build_master_data
from app.models import Facility, OperatingMode, Pipe, Pump, Sensor, Tank, Telemetry, Valve
from app.simulation.engine import OperatingSettings, run_process
from app.simulation.process_model import build_process_model, snapshot_from_objects
from app.simulation.sensors import derived_value, generate_readings

SCALES = {
    # name: (steps, step_minutes)
    "tiny": (48, 15),
    "starter": (96, 15),  # 1 day  -> 160 sensors x 96  = 15,360 records
    "full": (625, 15),  # 6.5 days -> 160 sensors x 625 = 100,000 records
}
START_TIME = datetime(2026, 10, 22, 0, 0, 0)


@dataclass
class GeneratedDataset:
    seed: int
    scale: str
    master: dict
    models: dict
    results: dict
    readings: dict
    timestamps: list
    step_minutes: int
    faults: list
    ground_truth: dict
    telemetry_rows: list


def generate_dataset(seed: int, scale: str) -> GeneratedDataset:
    if scale not in SCALES:
        raise ValueError(f"Unknown scale '{scale}'. Choose from {sorted(SCALES)}")
    n_steps, step_minutes = SCALES[scale]
    ss = np.random.SeedSequence(seed)
    master_ss, fault_ss, proc_ss, sens_ss = ss.spawn(4)
    master = build_master_data(np.random.default_rng(master_ss))

    models = {}
    for fac in master["facilities"]:
        def of(kind, fac_id=fac.id):
            return [r for r in master[kind] if r.facility_id == fac_id]
        cfg = snapshot_from_objects(fac.id, of("pumps"), of("tanks"), of("valves"), of("pipes"), of("sensors"))
        models[fac.id] = build_process_model(cfg)

    faults = build_fault_schedule(list(models.values()), n_steps, np.random.default_rng(fault_ss))

    results, readings = {}, {}
    proc_rngs = proc_ss.spawn(len(models))
    sens_rngs = sens_ss.spawn(len(models))
    timestamps = None
    for i, (fac_id, model) in enumerate(models.items()):
        mine = [f for f in faults if f.target_id in model.pipes or f.target_id in model.pumps
                or f.target_id in model.valves or f.target_id in model.sensors]
        res = run_process(model, n_steps, step_minutes, START_TIME, OperatingSettings(), mine,
                          np.random.default_rng(proc_rngs[i]))
        results[fac_id] = res
        readings[fac_id] = generate_readings(model, res, np.random.default_rng(sens_rngs[i]),
                                             [f for f in mine if f.kind == "SENSOR_FAULT"])
        timestamps = res["timestamps"]

    gt = build_ground_truth(models, results, faults, timestamps, step_minutes)
    gt.update({"seed": seed, "scale": scale})

    rows = []
    tel_id = 0
    for fac_id, model in models.items():
        for sid in sorted(readings[fac_id]):
            sensor = model.sensors[sid]
            tank = model.tanks.get(sensor["equipment_id"]) if sensor["equipment_type"] == "TANK" else None
            vals = readings[fac_id][sid]
            for t_i, ts in enumerate(timestamps):
                v = vals[t_i]
                value = None if np.isnan(v) else float(v)
                dv, du = derived_value(sensor, value, tank, step_minutes)
                tel_id += 1
                rows.append({"id": tel_id, "sensor_id": sid, "timestamp": ts, "value": value,
                             "derived_value": dv, "derived_unit": du, "source": "SYNTHETIC"})
    return GeneratedDataset(seed, scale, master, models, results, readings, timestamps, step_minutes,
                            faults, gt, rows)


# --------------------------------------------------------------------- persist
def persist_to_db(db: Session, ds: GeneratedDataset) -> None:
    m = ds.master
    db.execute(insert(OperatingMode), [r.as_dict() for r in m["operating_modes"]])
    db.execute(insert(Facility), [{**r.as_dict(), "created_at": START_TIME} for r in m["facilities"]])
    db.execute(insert(Tank), [r.as_dict() for r in m["tanks"]])
    db.execute(insert(Pump), [r.as_dict() for r in m["pumps"]])
    db.execute(insert(Valve), [r.as_dict() for r in m["valves"]])
    db.execute(insert(Pipe), [r.as_dict() for r in m["pipes"]])
    db.execute(insert(Sensor), [r.as_dict() for r in m["sensors"]])
    chunk = 20000
    for i in range(0, len(ds.telemetry_rows), chunk):
        db.execute(insert(Telemetry), ds.telemetry_rows[i:i + chunk])
    db.commit()


def _write_csv(path: Path, rows: list[dict], fields: list[str]) -> str:
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow({k: ("" if r.get(k) is None else (r[k].isoformat() if isinstance(r.get(k), datetime) else r[k]))
                        for k in fields})
    return hashlib.sha256(path.read_bytes()).hexdigest()


def export_files(ds: GeneratedDataset, out_dir: Path | None = None) -> dict:
    out = Path(out_dir or GENERATED_DIR / ds.scale)
    out.mkdir(parents=True, exist_ok=True)
    hashes = {}
    for kind in ("operating_modes", "facilities", "pumps", "tanks", "valves", "pipes", "sensors"):
        rows = [r.as_dict() for r in ds.master[kind]]
        hashes[f"{kind}.csv"] = _write_csv(out / f"{kind}.csv", rows, list(rows[0].keys()))
    hashes["telemetry.csv"] = _write_csv(out / "telemetry.csv", ds.telemetry_rows,
                                         ["id", "sensor_id", "timestamp", "value", "derived_value", "derived_unit",
                                          "source"])
    gt_json = out / "ground_truth.json"
    gt_json.write_text(json.dumps(ds.ground_truth, indent=2), encoding="utf-8")
    hashes["ground_truth.json"] = hashlib.sha256(gt_json.read_bytes()).hexdigest()
    gt_fields = ["scenario_id", "facility_id", "equipment_type", "equipment_id", "issue_type", "sub_type",
                 "start_timestamp", "end_timestamp", "expected_detection", "expected_severity", "magnitude",
                 "injection_id", "injection_rule"]
    hashes["ground_truth.csv"] = _write_csv(out / "ground_truth.csv", ds.ground_truth["labels"], gt_fields)
    counts = {k: len(v) for k, v in ds.master.items()}
    counts["telemetry"] = len(ds.telemetry_rows)
    counts["ground_truth_labels"] = len(ds.ground_truth["labels"])
    manifest = {
        "seed": ds.seed, "scale": ds.scale, "steps": len(ds.timestamps), "step_minutes": ds.step_minutes,
        "start": ds.timestamps[0].isoformat(), "end": ds.timestamps[-1].isoformat(), "counts": counts,
        "injected_events": [f.to_dict() for f in ds.faults], "sha256": hashes,
        "dataset_fingerprint": hashlib.sha256("".join(hashes[k] for k in sorted(hashes)).encode()).hexdigest(),
        "model_issues": {fid: m.issues for fid, m in ds.models.items()},
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest
