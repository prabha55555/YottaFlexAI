"""End-to-end smoke test of the running application (reviewer verification).

Exercises every API endpoint against a running backend: reads, filters, exports, CRUD (including
the rejections a reviewer should see), a simulation with baseline comparison, the alarm lifecycle,
evaluation and negative scenarios. Test entities it creates are deleted again; it does add one
simulation run (+ baseline + one deliberately FAILED run) and closes that simulation's first alarm.

Usage (from backend/, with the API running and the full dataset loaded):
    python -m scripts.smoke_test                              # http://localhost:8000/api
    python -m scripts.smoke_test http://localhost:5173/api    # through the frontend proxy
"""
import json
import sys
import urllib.error
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000/api"
results = []


def call(method, path, body=None, expect=(200,)):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"} if data else {})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            status, raw, ctype = r.status, r.read(), r.headers.get("Content-Type", "")
    except urllib.error.HTTPError as e:
        status, raw, ctype = e.code, e.read(), e.headers.get("Content-Type", "")
    ok = status in expect
    results.append((ok, method, path, status))
    if "json" in ctype and raw:
        return status, json.loads(raw)
    return status, raw


def check(label, cond):
    results.append((bool(cond), "CHECK", label, ""))


# --- system / master data
_, h = call("GET", "/health")
check("health: 100,000 telemetry rows", h["telemetry_records"] == 100000)
_, facs = call("GET", "/facilities")
check("3 facilities", len(facs) == 3)
call("GET", "/facilities/FAC-001")
_, s = call("GET", "/facilities/FAC-001/summary")
check("FAC-001 has 7 pumps", s["counts"]["pumps"] == 7)
call("GET", "/operating-modes")
for kind, total in (("pumps", 20), ("tanks", 30), ("valves", 60), ("pipes", 100), ("sensors", 160)):
    _, p = call("GET", f"/{kind}?limit=5")
    check(f"{kind} total = {total}", p["total"] == total)
    call("GET", f"/{kind}/{p['items'][0]['id']}")
call("GET", "/pumps?facility_id=FAC-002&q=Pump&skip=2&limit=2")
call("GET", "/sensors?filter=LEVEL")

# --- telemetry
_, rng = call("GET", "/telemetry/range")
call("GET", "/telemetry?facility_id=FAC-001&sensor_type=FLOW&start=2026-10-23T00:00:00&end=2026-10-23T06:00:00&limit=10")
call("GET", "/telemetry?start=2026-10-23T06:00:00&end=2026-10-23T00:00:00", expect=(422,))
_, ser = call("GET", "/telemetry/series?facility_id=FAC-001&sensor_ids=SNS-001,SNS-005&max_points=100")
check("series returns 2 sensors", len(ser["series"]) == 2)
_, snap = call("GET", "/telemetry/snapshot?facility_id=FAC-002&at=2026-10-24T12:00:00")
check("snapshot has 54 readings", len(snap["readings"]) == 54)
call("GET", "/telemetry/export?sensor_id=SNS-001&format=csv")
call("GET", "/telemetry/export?sensor_id=SNS-001&format=json")

# --- topology, mass balance, dashboard, analytics
for f in ("FAC-001", "FAC-002", "FAC-003"):
    _, t = call("GET", f"/topology/{f}")
    check(f"topology {f} valid", t["validation"]["is_valid"])
call("GET", "/topology/FAC-999", expect=(404,))
_, mb = call("GET", "/mass-balance?facility_id=FAC-002&window_hours=24&tolerance_pct=2")
check("mass balance has windows", len(mb["windows"]) >= 6)
call("GET", "/dashboard/summary")
call("GET", "/dashboard/summary?facility_id=FAC-003")
call("GET", "/analytics/overview?facility_id=FAC-001")

# --- anomalies
_, an = call("GET", "/anomalies?source=TELEMETRY_SCAN&limit=100")
check("telemetry-scan anomalies present", an["total"] > 0)
call("GET", f"/anomalies/{an['items'][0]['id']}")
call("GET", "/anomalies/stats")
_, sc = call("POST", "/anomalies/scan?facility_id=FAC-001")
check("re-scan is idempotent (0 new)", sc["FAC-001"]["new"] == 0)
call("GET", "/anomalies/export?format=csv")
call("GET", "/anomalies/export?format=json")

# --- evaluation & validation
_, ev = call("GET", "/evaluation/metrics")
check("evaluation available with F1", ev["available"] and ev["overall"]["f1_score"] is not None)
call("GET", "/evaluation/ground-truth")
_, dq = call("GET", "/evaluation/data-quality")
check("PK/FK/duplicates all clean", dq["primary_key_errors"] == 0 and dq["foreign_key_errors"] == 0 and dq["duplicate_count"] == 0)
call("GET", "/validation/report")
_, neg = call("GET", "/validation/negative-scenarios")
check("5/5 negative scenarios caught", neg["caught"] == 5)

# --- simulations
_, scen = call("GET", "/simulations/scenarios?facility_id=FAC-002")
check("8 scenarios", len(scen["scenarios"]) == 8)
st, sim = call("POST", "/simulations", {"facility_id": "FAC-002", "scenario": "PUMP_DEGRADATION", "steps": 96,
                                        "name": "smoke test"}, expect=(201,))
check("simulation detected PUMP_DEGRADATION", sim["summary"]["anomalies_by_type"].get("PUMP_DEGRADATION", 0) >= 1)
check("simulation has baseline", bool(sim["baseline_simulation_id"]))
call("GET", f"/simulations/{sim['id']}")
call("GET", "/simulations?facility_id=FAC-002&limit=5")
_, cmp_ = call("GET", f"/simulations/compare?baseline_id={sim['baseline_simulation_id']}&modified_id={sim['id']}")
check("comparison shows energy delta", "pump_energy_kwh" in cmp_["kpis"])
for q in ("format=json", "format=csv&content=timeseries", "format=csv&content=readings"):
    call("GET", f"/simulations/{sim['id']}/export?{q}")
st, bad = call("POST", "/simulations", {"facility_id": "FAC-001", "scenario": "NORMAL",
                                        "parameters": {"valve_openings": {"VALVE-001": 150}}}, expect=(422,))
check("invalid simulation rejected with field error", bad["detail"]["errors"][0]["field"] == "valve_openings.VALVE-001")

# --- alarms lifecycle
_, al = call("GET", f"/alarms?simulation_id={sim['id']}")
aid = al["items"][0]["id"]
call("POST", f"/alarms/{aid}/resolve", {"actor": "smoke"}, expect=(409,))
call("POST", f"/alarms/{aid}/acknowledge", {"actor": "smoke", "note": "ack"})
call("POST", f"/alarms/{aid}/resolve", {"actor": "smoke"})
_, d = call("POST", f"/alarms/{aid}/close", {"actor": "smoke"})
check("alarm history ACTIVE>ACK>RESOLVED>CLOSED", [e["to_status"] for e in d["events"]] ==
      ["ACTIVE", "ACKNOWLEDGED", "RESOLVED", "CLOSED"])
call("GET", "/alarms?status=ACTIVE,ACKNOWLEDGED&source=LIVE&severity=CRITICAL,HIGH")
call("GET", "/alarms/stats")
call("GET", "/alarms/export?format=csv")
call("GET", "/alarms/export?format=json")

# --- CRUD round trip (cleaned up afterwards)
_, fac = call("POST", "/facilities", {"name": "Smoke Test Facility", "location": "Test"}, expect=(201,))
call("PUT", f"/facilities/{fac['id']}", {"status": "MAINTENANCE"})
_, tank = call("POST", "/tanks", {"facility_id": fac["id"], "name": "Smoke Tank", "capacity_m3": 500, "height_m": 5},
               expect=(201,))
_, pump = call("POST", "/pumps", {"facility_id": fac["id"], "name": "Smoke Pump", "rated_flow_m3h": 50,
                                  "shutoff_head_m": 30, "curve_k": 0.002}, expect=(201,))
call("POST", "/pipes", {"facility_id": fac["id"], "name": "Bad pipe", "from_node_type": "PUMP",
                        "from_node_id": "PUMP-999", "to_node_type": "TANK", "to_node_id": tank["id"], "length_m": 10,
                        "diameter_mm": 100, "max_flow_m3h": 50}, expect=(422,))
_, pipe = call("POST", "/pipes", {"facility_id": fac["id"], "name": "Smoke pipe", "from_node_type": "TANK",
                                  "from_node_id": tank["id"], "to_node_type": "PUMP", "to_node_id": pump["id"],
                                  "length_m": 10, "diameter_mm": 100, "max_flow_m3h": 50}, expect=(201,))
_, sens = call("POST", "/sensors", {"facility_id": fac["id"], "name": "Smoke LT", "tag": "LT-SMOKE",
                                    "equipment_type": "TANK", "equipment_id": tank["id"], "sensor_type": "LEVEL",
                                    "measurement_point": "LEVEL", "unit": "%", "min_range": 0, "max_range": 100},
               expect=(201,))
call("PUT", f"/tanks/{tank['id']}", {"initial_level_pct": 120}, expect=(422,))
call("DELETE", f"/tanks/{tank['id']}", expect=(409,))  # in use by pipe + sensor
call("DELETE", f"/facilities/{fac['id']}", expect=(409,))  # not empty
for kind, obj in (("sensors", sens), ("pipes", pipe), ("pumps", pump), ("tanks", tank)):
    call("DELETE", f"/{kind}/{obj['id']}", expect=(204,))
call("DELETE", f"/facilities/{fac['id']}", expect=(204,))
call("GET", f"/facilities/{fac['id']}", expect=(404,))

failed = [r for r in results if not r[0]]
for r in failed:
    print("FAIL", r)
calls = sum(1 for r in results if r[1] != "CHECK")
checks = sum(1 for r in results if r[1] == "CHECK")
print(f"{calls} API calls, {checks} data checks -> {len(results) - len(failed)}/{len(results)} passed")
sys.exit(1 if failed else 0)
