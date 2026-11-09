"""Detection evaluation against ground truth (window-based confusion matrix).

Evaluation unit: (issue type, equipment, 6-hour window). A unit is
* ground-truth positive if any label of that type/equipment overlaps the window,
* predicted positive if any TELEMETRY_SCAN anomaly of that type/equipment overlaps it.
Every other unit in the candidate universe is a negative, which gives a real
true-negative count. Equipment key: sensor_id for SENSOR_FAULT, equipment_id otherwise.

Ground truth is read only here (never by the detector).
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.anomaly_detection.rules import EVALUATED_TYPES
from app.config import GENERATED_DIR
from app.models import Anomaly, Pipe, Pump, Sensor, Tank

WINDOW_HOURS = 6
ACTIVE_DATASET_FILE = GENERATED_DIR / "active_dataset.json"


def active_dataset() -> dict | None:
    if ACTIVE_DATASET_FILE.exists():
        return json.loads(ACTIVE_DATASET_FILE.read_text(encoding="utf-8"))
    return None


def load_ground_truth(path: Path | None = None) -> dict | None:
    if path is None:
        info = active_dataset()
        if not info:
            return None
        path = GENERATED_DIR / info["scale"] / "ground_truth.json"
    if not Path(path).exists():
        return None
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _overlaps(a0: datetime, a1: datetime, b0: datetime, b1: datetime) -> bool:
    return a0 < b1 and b0 < a1


def _prf(tp: int, fp: int, fn: int) -> dict:
    p = tp / (tp + fp) if tp + fp else None
    r = tp / (tp + fn) if tp + fn else None
    f1 = 2 * p * r / (p + r) if p is not None and r is not None and (p + r) > 0 else None
    return {"precision": None if p is None else round(p, 4), "recall": None if r is None else round(r, 4),
            "f1_score": None if f1 is None else round(f1, 4)}


def candidate_universe(db: Session) -> dict[str, set[str]]:
    monitored_pipes = set(db.scalars(select(Sensor.equipment_id).where(Sensor.equipment_type == "PIPE")).all())
    return {
        "LEAK": monitored_pipes or set(db.scalars(select(Pipe.id)).all()),
        "BLOCKAGE": monitored_pipes or set(db.scalars(select(Pipe.id)).all()),
        "PUMP_DEGRADATION": set(db.scalars(select(Pump.id)).all()),
        "SENSOR_FAULT": set(db.scalars(select(Sensor.id)).all()),
        "TANK_OVERCAPACITY": set(db.scalars(select(Tank.id)).all()),
    }


def evaluate(db: Session, gt: dict | None = None) -> dict:
    gt = gt or load_ground_truth()
    if gt is None:
        return {"available": False, "message": "No ground truth found. Run scripts.generate_data first."}
    labels = gt["labels"]
    step = timedelta(minutes=gt["step_minutes"])
    start = datetime.fromisoformat(gt["start"])
    end = datetime.fromisoformat(gt["end"]) + step
    windows = []
    w = start
    while w < end:
        windows.append((w, min(w + timedelta(hours=WINDOW_HOURS), end)))
        w += timedelta(hours=WINDOW_HOURS)

    preds = db.scalars(select(Anomaly).where(Anomaly.source == "TELEMETRY_SCAN",
                                             Anomaly.anomaly_type.in_(EVALUATED_TYPES))).all()
    universe = candidate_universe(db)

    def key_of_anomaly(a: Anomaly) -> str:
        return a.sensor_id if a.anomaly_type == "SENSOR_FAULT" and a.sensor_id else a.equipment_id

    per_type = {}
    total = {"tp": 0, "fp": 0, "tn": 0, "fn": 0}
    event_level = {}
    for itype in EVALUATED_TYPES:
        lab = [x for x in labels if x["issue_type"] == itype and x["expected_detection"]]
        prd = [p for p in preds if p.anomaly_type == itype]
        keys = set(universe[itype]) | {x["equipment_id"] for x in lab} | {key_of_anomaly(p) for p in prd}
        lab_by_key: dict[str, list] = {}
        for x in lab:
            lab_by_key.setdefault(x["equipment_id"], []).append(
                (datetime.fromisoformat(x["start_timestamp"]), datetime.fromisoformat(x["end_timestamp"]) + step))
        prd_by_key: dict[str, list] = {}
        for p in prd:
            prd_by_key.setdefault(key_of_anomaly(p), []).append((p.start_time, p.end_time + step))
        tp = fp = tn = fn = 0
        for k in keys:
            for w0, w1 in windows:
                g = any(_overlaps(a, b, w0, w1) for a, b in lab_by_key.get(k, []))
                d = any(_overlaps(a, b, w0, w1) for a, b in prd_by_key.get(k, []))
                if g and d:
                    tp += 1
                elif d:
                    fp += 1
                elif g:
                    fn += 1
                else:
                    tn += 1
        # event level: each label detected? latency, severity agreement
        detected = 0
        latencies = []
        sev_match = 0
        details = []
        for x in lab:
            ls = datetime.fromisoformat(x["start_timestamp"])
            le = datetime.fromisoformat(x["end_timestamp"]) + step
            hits = [p for p in prd if key_of_anomaly(p) == x["equipment_id"] and _overlaps(p.start_time, p.end_time + step, ls, le)]
            if hits:
                detected += 1
                first = min(hits, key=lambda p: p.detected_at)
                latencies.append((first.detected_at - ls).total_seconds() / 60)
                rank = {"LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}
                top = max(hits, key=lambda p: rank[p.severity]).severity
                if top == x["expected_severity"]:
                    sev_match += 1
                details.append({"scenario_id": x["scenario_id"], "equipment_id": x["equipment_id"],
                                 "sub_type": x.get("sub_type"), "detected": True, "anomaly_ids": [h.id for h in hits],
                                 "latency_min": round(latencies[-1], 1), "expected_severity": x["expected_severity"],
                                 "detected_severity": top})
            else:
                details.append({"scenario_id": x["scenario_id"], "equipment_id": x["equipment_id"],
                                "sub_type": x.get("sub_type"), "detected": False, "anomaly_ids": [],
                                "latency_min": None, "expected_severity": x["expected_severity"],
                                "detected_severity": None})
        unmatched_preds = [p.id for p in prd if not any(
            x["equipment_id"] == key_of_anomaly(p) and _overlaps(
                p.start_time, p.end_time + step, datetime.fromisoformat(x["start_timestamp"]),
                datetime.fromisoformat(x["end_timestamp"]) + step) for x in lab)]
        per_type[itype] = {"tp": tp, "fp": fp, "tn": tn, "fn": fn, **_prf(tp, fp, fn),
                           "units": len(keys) * len(windows), "labels": len(lab), "predictions": len(prd)}
        event_level[itype] = {
            "labels": len(lab), "detected": detected,
            "event_recall": round(detected / len(lab), 4) if lab else None,
            "mean_latency_min": round(sum(latencies) / len(latencies), 1) if latencies else None,
            "severity_agreement": round(sev_match / detected, 4) if detected else None,
            "unmatched_predictions": unmatched_preds, "details": details,
        }
        for k in total:
            total[k] += per_type[itype][k]

    # Misclassification check: sensor faults that were labelled as process LEAKs
    sensors = {s.id: s for s in db.scalars(select(Sensor)).all()}
    misclassified = []
    for x in labels:
        if x["issue_type"] != "SENSOR_FAULT":
            continue
        s = sensors.get(x["equipment_id"])
        if not s:
            continue
        ls = datetime.fromisoformat(x["start_timestamp"])
        le = datetime.fromisoformat(x["end_timestamp"]) + step
        for p in preds:
            if p.anomaly_type == "LEAK" and p.equipment_id == s.equipment_id and _overlaps(p.start_time, p.end_time, ls, le):
                misclassified.append({"scenario_id": x["scenario_id"], "sensor_id": s.id, "anomaly_id": p.id})
    return {
        "available": True, "window_hours": WINDOW_HOURS, "windows": len(windows), "seed": gt.get("seed"),
        "scale": gt.get("scale"), "per_type": per_type,
        "overall": {**total, **_prf(total["tp"], total["fp"], total["fn"]),
                    "accuracy": round((total["tp"] + total["tn"]) / max(sum(total.values()), 1), 4)},
        "event_level": event_level,
        "sensor_faults_labelled_as_process": misclassified,
        "method": "Window-based confusion matrix; unit = (issue type, equipment, 6 h window). Ground truth is "
                  "loaded only for evaluation.",
    }
