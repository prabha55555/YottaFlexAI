"""Deliberate negative scenarios (kept in backend/negative_cases/, never loaded
into the baseline database). Each case runs the *production* validator on an
invalid input and reports whether the validator caught it and why.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import numpy as np

from app.anomaly_detection.detector import Detector
from app.config import MASS_BALANCE_TOLERANCE_PCT, NEGATIVE_CASES_DIR
from app.services.mass_balance import status_for
from app.simulation.engine import FaultEvent, OperatingSettings, run_process
from app.simulation.process_model import build_process_model
from app.simulation.sensors import generate_readings
from app.topology.graph import analyse_graph, build_graph


def _load(name: str) -> dict:
    return json.loads((NEGATIVE_CASES_DIR / name).read_text(encoding="utf-8"))


def validate_tank_readings(tank: dict, readings: list[dict]) -> list[dict]:
    errors = []
    for r in readings:
        lvl = r["level_pct"]
        vol = lvl / 100 * tank["capacity_m3"]
        if lvl > 100 or vol > tank["capacity_m3"]:
            errors.append({"code": "VOLUME_EXCEEDS_CAPACITY", "timestamp": r["timestamp"],
                           "message": f"Level {lvl}% implies {vol:.1f} m3 stored in {tank['id']} whose capacity is "
                                      f"{tank['capacity_m3']} m3 (excess {vol - tank['capacity_m3']:.1f} m3). A closed "
                                      "tank cannot hold more than its capacity: overflow or instrument fault."})
        elif lvl < 0:
            errors.append({"code": "NEGATIVE_LEVEL", "timestamp": r["timestamp"],
                           "message": f"Level {lvl}% is below 0 %."})
    return errors


def validate_balance(case: dict) -> list[dict]:
    inflow, outflow, ds = case["total_inflow_m3"], case["total_outflow_m3"], case["storage_change_m3"]
    tol = case.get("tolerance_pct", MASS_BALANCE_TOLERANCE_PCT)
    residual = inflow - outflow - ds
    err = abs(residual) / inflow * 100 if inflow else float("inf")
    status = status_for(err, tol)
    if status in ("WARNING", "EXCEPTION"):
        cls = "MEASUREMENT_FAULT" if case.get("boundary_sensor_faults") else "PROCESS_IMBALANCE"
        return [{"code": "MASS_BALANCE_EXCEPTION" if status == "EXCEPTION" else "MASS_BALANCE_WARNING",
                 "message": f"Inflow {inflow} - outflow {outflow} - storage change {ds} = residual {residual:.1f} m3 "
                            f"= {err:.2f}% of inflow, exceeding the {tol}% tolerance. Classified as {cls}: "
                            "flow is not conserved within the facility boundary.",
                 "balance_error_pct": round(err, 3), "classification": cls}]
    return []


def validate_simulation_record(sim: dict) -> list[dict]:
    errors = []
    if sim.get("status") == "COMPLETED" and sim.get("summary"):
        for key in ("original_config", "modified_parameters", "effective_config"):
            if not sim.get(key):
                errors.append({"code": "MISSING_INPUT_CONFIGURATION", "field": key,
                               "message": f"Simulation {sim['id']} has outputs but no '{key}'. Results cannot be "
                                          "traced to their inputs or reproduced; the run is rejected."})
    return errors


def check_classification(case: dict) -> tuple[list[dict], dict]:
    plant = _load(case["plant_fixture"])["config"]
    model = build_process_model(plant)
    ln = model.lines[0]
    sid = ln.sensors[case["fault"]["sensor_role"]]
    steps, step_min = case["steps"], case["step_minutes"]
    fault = FaultEvent("SENSOR_FAULT", sid, case["fault"]["start_step"], steps, case["fault"]["magnitude"],
                       case["fault"]["mode"])
    proc_ss, sens_ss = np.random.SeedSequence(case["seed"]).spawn(2)
    res = run_process(model, steps, step_min, datetime(2026, 10, 22), OperatingSettings(), [],
                      np.random.default_rng(proc_ss))
    readings = generate_readings(model, res, np.random.default_rng(sens_ss), [fault])
    det = Detector(model).detect(readings, res["timestamps"], step_min)
    # naive classification: imbalance => leak
    up, dn = readings[ln.sensors["flow_up"]], readings[ln.sensors["flow_down"]]
    imb = float(np.nanmean((up[fault.start_step:] - dn[fault.start_step:]) / up[fault.start_step:]))
    recon = [a for a in det.anomalies if a["detection_rule"] == "FLOW_RECONCILIATION"]
    leaks = [a for a in det.anomalies if a["anomaly_type"] == "LEAK"]
    evidence = {"naive_imbalance_pct": round(imb * 100, 2), "faulty_sensor": sid,
                "detector_classification": "SENSOR_FAULT" if recon else ("LEAK" if leaks else "NONE"),
                "reconciliation_evidence": recon[0]["evidence"] if recon else None}
    errors = []
    claimed = case["claimed_label"]["issue_type"]
    if claimed == "LEAK" and recon and not leaks:
        ev = recon[0]["evidence"]
        errors.append({"code": "MISCLASSIFIED_SENSOR_FAULT",
                       "message": f"Label '{claimed}' rejected: {sid} reads {imb * 100:.1f}% below the pump meter, but "
                                  f"the receiving tank's level change matches the UPSTREAM flow (residual "
                                  f"{ev.get('dst_tank_residual_if_upstream_meter_true_m3')} m3) far better than the "
                                  f"downstream reading (residual {ev.get('dst_tank_residual_if_downstream_meter_true_m3')} "
                                  "m3). No water was lost: this is an instrument (sensor) fault, not a process leak."})
    return errors, evidence


def run_case(path: Path) -> dict:
    case = json.loads(path.read_text(encoding="utf-8"))
    check = case["check"]
    evidence: dict = {}
    if check == "topology":
        g, issues = build_graph(case["nodes"], case["pipes"])
        analysis = analyse_graph(g)
        errors = [i for i in issues + analysis["issues"] if i["severity"] == "ERROR"]
        errors = [{"code": e["code"], "message": e["message"], "equipment_id": e["equipment_id"]} for e in errors]
    elif check == "tank_capacity":
        errors = validate_tank_readings(case["tank"], case["readings"])
    elif check == "mass_balance":
        errors = validate_balance(case)
    elif check == "simulation_record":
        errors = validate_simulation_record(case["simulation"])
    elif check == "classification":
        errors, evidence = check_classification(case)
    else:
        errors = [{"code": "UNKNOWN_CHECK", "message": check}]
    caught = any(e["code"] == case["expected_error_code"] for e in errors)
    return {
        "case_id": case["case_id"], "title": case["title"], "description": case["description"],
        "check": check, "expected_error_code": case["expected_error_code"],
        "validation_status": "FAILED" if errors else "PASSED",
        "detected_as_expected": caught, "errors": errors, "evidence": evidence, "fixture": path.name,
    }


def run_all() -> dict:
    cases = [run_case(p) for p in sorted(NEGATIVE_CASES_DIR.glob("NEG-*.json"))]
    return {"cases": cases, "total": len(cases), "caught": sum(1 for c in cases if c["detected_as_expected"]),
            "note": "Negative fixtures live in backend/negative_cases/ and are never written to the baseline database."}
