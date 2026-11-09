"""API workflows: CRUD, topology, simulation reproducibility, alarm lifecycle,
evaluation and negative scenarios."""
from __future__ import annotations

from app.models import Alarm, AlarmEvent, SimulationRun


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json()["facilities"] == 3


def test_facility_crud(client):
    r = client.post("/api/facilities", json={"name": "Test Facility X", "location": "Lab"})
    assert r.status_code == 201
    fid = r.json()["id"]
    assert fid == "FAC-004"
    assert client.put(f"/api/facilities/{fid}", json={"status": "MAINTENANCE"}).json()["status"] == "MAINTENANCE"
    assert client.post("/api/facilities", json={"name": "Test Facility X"}).status_code == 409
    assert client.delete(f"/api/facilities/{fid}").status_code == 204
    assert client.get(f"/api/facilities/{fid}").status_code == 404


def test_equipment_crud_and_validation(client):
    tank = client.post("/api/tanks", json={"facility_id": "FAC-001", "name": "Test Tank", "capacity_m3": 500,
                                           "height_m": 6}).json()
    assert tank["id"] == "TANK-031"
    # tank level above capacity is rejected
    r = client.put(f"/api/tanks/{tank['id']}", json={"initial_level_pct": 120})
    assert r.status_code == 422
    # pipe referencing a missing node is rejected with an explanation
    r = client.post("/api/pipes", json={"facility_id": "FAC-001", "name": "Bad", "from_node_type": "PUMP",
                                        "from_node_id": "PUMP-999", "to_node_type": "TANK", "to_node_id": tank["id"],
                                        "length_m": 10, "diameter_mm": 100, "max_flow_m3h": 50})
    assert r.status_code == 422 and r.json()["detail"]["error"] == "MISSING_NODE"
    # cross-facility pipe rejected
    r = client.post("/api/pipes", json={"facility_id": "FAC-001", "name": "Cross", "from_node_type": "TANK",
                                        "from_node_id": "TANK-030", "to_node_type": "TANK", "to_node_id": tank["id"],
                                        "length_m": 10, "diameter_mm": 100, "max_flow_m3h": 50})
    assert r.status_code == 422
    # sensor on missing equipment rejected
    r = client.post("/api/sensors", json={"facility_id": "FAC-001", "name": "S", "tag": "LT-999",
                                          "equipment_type": "TANK", "equipment_id": "TANK-999", "sensor_type": "LEVEL",
                                          "measurement_point": "LEVEL", "unit": "%", "min_range": 0, "max_range": 100})
    assert r.status_code == 422
    # equipment in use cannot be deleted
    assert client.delete("/api/pumps/PUMP-001").status_code == 409
    assert client.delete(f"/api/tanks/{tank['id']}").status_code == 204
    page = client.get("/api/pumps", params={"facility_id": "FAC-001", "limit": 3}).json()
    assert page["total"] == 7 and len(page["items"]) == 3


def test_topology_from_database(client):
    t = client.get("/api/topology/FAC-001").json()
    assert t["summary"]["pumps"] == 7 and t["summary"]["tanks"] == 10
    assert t["validation"]["is_valid"] is True
    assert len(t["validation"]["components"]) == 3  # three process trains
    assert t["validation"]["supply_to_demand_paths"]
    assert all(e["valid"] for e in t["edges"])


def test_topology_detects_missing_node_and_isolated_node():
    from app.topology.graph import analyse_graph, build_graph
    nodes = [{"id": "TANK-1", "node_type": "TANK", "facility_id": "F"},
             {"id": "VALVE-1", "node_type": "VALVE", "role": "INLINE", "facility_id": "F"},
             {"id": "TANK-2", "node_type": "TANK", "facility_id": "F"}]
    pipes = [{"id": "P1", "facility_id": "F", "from_node_id": "TANK-1", "to_node_id": "PUMP-X",
              "from_node_type": "TANK", "to_node_type": "PUMP"}]
    g, issues = build_graph(nodes, pipes)
    codes = {i["code"] for i in issues + analyse_graph(g)["issues"]}
    assert {"MISSING_NODE", "ISOLATED_NODE"} <= codes


def test_simulation_reproducible_and_never_overwritten(client, db):
    body = {"facility_id": "FAC-002", "scenario": "LEAKAGE", "steps": 48, "run_baseline": True}
    a = client.post("/api/simulations", json=body)
    b = client.post("/api/simulations", json=body)
    assert a.status_code == b.status_code == 201
    a, b = a.json(), b.json()
    assert a["id"] != b["id"] and a["id"].startswith("SIM-2026-")
    assert a["input_hash"] == b["input_hash"]
    assert a["summary"] == b["summary"]
    assert a["timeseries"] == b["timeseries"]
    assert a["original_config"] and a["modified_parameters"] and a["effective_config"] and a["assumptions"]
    assert a["summary"]["anomalies_by_type"].get("LEAK", 0) >= 1
    assert a["baseline_simulation_id"]
    cmp = client.get("/api/simulations/compare", params={"baseline_id": a["baseline_simulation_id"],
                                                         "modified_id": a["id"]}).json()
    assert cmp["kpis"]["true_leak_m3"]["modified"] > cmp["kpis"]["true_leak_m3"]["baseline"]
    alarms = client.get("/api/alarms", params={"simulation_id": a["id"]}).json()
    assert alarms["total"] >= 1
    # exports
    assert client.get(f"/api/simulations/{a['id']}/export", params={"format": "csv"}).status_code == 200
    assert client.get(f"/api/simulations/{a['id']}/export", params={"format": "json"}).status_code == 200
    assert db.get(SimulationRun, a["id"]) is not None and db.get(SimulationRun, b["id"]) is not None


def test_all_scenarios_execute(client):
    for sc in ("NORMAL", "BLOCKAGE", "PUMP_DEGRADATION", "SENSOR_MALFUNCTION", "HIGH_DEMAND", "VALVE_CLOSURE",
               "TANK_OVERCAPACITY"):
        r = client.post("/api/simulations", json={"facility_id": "FAC-003", "scenario": sc, "steps": 48,
                                                  "run_baseline": False})
        assert r.status_code == 201, (sc, r.text)
        kp = r.json()["summary"]["anomalies_by_type"]
        expected = {"BLOCKAGE": "BLOCKAGE", "PUMP_DEGRADATION": "PUMP_DEGRADATION",
                    "SENSOR_MALFUNCTION": "SENSOR_FAULT", "VALVE_CLOSURE": "ABNORMAL_FLOW",
                    "TANK_OVERCAPACITY": "TANK_OVERCAPACITY"}.get(sc)
        if expected:
            assert kp.get(expected, 0) >= 1, (sc, kp)


def test_invalid_simulation_is_recorded_as_failed(client, db):
    r = client.post("/api/simulations", json={"facility_id": "FAC-001", "scenario": "NORMAL", "steps": 48,
                                              "parameters": {"valve_openings": {"VALVE-001": 150},
                                                             "pump_speeds": {"PUMP-999": 50}}})
    assert r.status_code == 422
    d = r.json()["detail"]
    assert len(d["errors"]) == 2
    run = db.get(SimulationRun, d["simulation_id"])
    assert run.status == "FAILED" and run.validation_errors


def test_alarm_lifecycle(client, db):
    alarm = client.get("/api/alarms", params={"status": "ACTIVE", "limit": 1}).json()["items"][0]
    aid = alarm["id"]
    assert client.post(f"/api/alarms/{aid}/resolve", json={"actor": "op"}).status_code == 409  # must ack first
    r = client.post(f"/api/alarms/{aid}/acknowledge", json={"actor": "op1", "note": "seen"})
    assert r.status_code == 200 and r.json()["status"] == "ACKNOWLEDGED"
    assert client.post(f"/api/alarms/{aid}/resolve", json={"actor": "op2"}).json()["status"] == "RESOLVED"
    d = client.post(f"/api/alarms/{aid}/close", json={"actor": "sup"}).json()
    assert d["status"] == "CLOSED"
    assert [e["to_status"] for e in d["events"]] == ["ACTIVE", "ACKNOWLEDGED", "RESOLVED", "CLOSED"]
    assert d["acknowledged_by"] == "op1" and d["closed_at"]
    assert db.query(AlarmEvent).filter(AlarmEvent.alarm_id == aid).count() == 4
    assert client.post(f"/api/alarms/{aid}/acknowledge", json={"actor": "x"}).status_code == 409
    assert db.get(Alarm, aid).anomaly_id is not None


def test_evaluation_metrics(client):
    ev = client.get("/api/evaluation/metrics").json()
    assert ev["available"]
    o = ev["overall"]
    total = o["tp"] + o["fp"] + o["tn"] + o["fn"]
    assert total == sum(v["units"] for v in ev["per_type"].values())
    for v in ev["per_type"].values():
        if v["tp"] + v["fp"]:
            assert v["precision"] == round(v["tp"] / (v["tp"] + v["fp"]), 4)
    dq = client.get("/api/evaluation/data-quality").json()
    assert dq["primary_key_errors"] == 0 and dq["foreign_key_errors"] == 0
    assert dq["topology_valid_facilities"] == 3


def test_evaluation_counts_are_correct_for_synthetic_case(db):
    from app.services.evaluation_service import evaluate
    gt = {"labels": [], "step_minutes": 15, "start": "2026-10-22T00:00:00", "end": "2026-10-22T11:45:00"}
    ev = evaluate(db, gt)
    # no labels: every prediction in the window is a false positive, no false negatives
    assert all(v["fn"] == 0 and v["tp"] == 0 for v in ev["per_type"].values())


def test_negative_scenarios_all_caught(client):
    r = client.get("/api/validation/negative-scenarios").json()
    assert r["total"] == 5 and r["caught"] == 5
    codes = {c["case_id"]: c["expected_error_code"] for c in r["cases"]}
    assert codes["NEG-005"] == "MISCLASSIFIED_SENSOR_FAULT"


def test_validation_report_and_exports(client):
    rep = client.get("/api/validation/report").json()
    for k in ("primary_keys", "foreign_keys", "topology", "tank_capacity", "mass_balance", "sensor_readings",
              "simulations"):
        assert k in rep
    assert client.get("/api/telemetry/export", params={"facility_id": "FAC-001", "format": "csv"}).status_code == 200
    j = client.get("/api/anomalies/export", params={"format": "json"})
    assert j.status_code == 200 and isinstance(j.json(), list)
    assert client.get("/api/telemetry", params={"start": "2026-10-22T05:00:00", "end": "2026-10-22T04:00:00"}
                      ).status_code == 422
    rng = client.get("/api/telemetry/range").json()
    assert rng["records"] > 0 and rng["simulated"] is True


def test_dashboard_and_analytics(client):
    d = client.get("/api/dashboard/summary").json()
    assert d["totals"]["facilities"] == 3 and d["totals"]["pumps"] == 20
    a = client.get("/api/analytics/overview", params={"facility_id": "FAC-001"}).json()
    assert len(a["equipment_health"]) == 7 and len(a["tank_utilisation"]) == 10
    mb = client.get("/api/mass-balance", params={"facility_id": "FAC-001", "window_hours": 6}).json()
    assert mb["status"] in ("BALANCED", "WARNING", "EXCEPTION") and mb["windows"]
