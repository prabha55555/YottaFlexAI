"""Service-layer enforcement of polymorphic equipment references.

SQLite cannot express "pipe.from_node_id references pumps OR tanks OR valves",
so every create/update of a pipe or sensor is checked here and rejected with an
explanatory 422 error when a reference is missing or crosses facilities.
"""
from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import Facility, Pipe, Pump, Sensor, Tank, Valve

NODE_MODELS = {"PUMP": Pump, "TANK": Tank, "VALVE": Valve}
SENSOR_TARGETS = {"PUMP": Pump, "TANK": Tank, "VALVE": Valve, "PIPE": Pipe}
SENSOR_RULES = {
    # sensor_type -> allowed equipment types
    "FLOW": {"PUMP", "PIPE", "VALVE"},
    "PRESSURE": {"PUMP", "PIPE", "VALVE"},
    "LEVEL": {"TANK"},
}


def require_facility(db: Session, facility_id: str) -> Facility:
    fac = db.get(Facility, facility_id)
    if fac is None:
        raise HTTPException(status_code=422, detail={
            "error": "FOREIGN_KEY_VIOLATION", "field": "facility_id",
            "message": f"Facility '{facility_id}' does not exist."})
    return fac


def check_node(db: Session, node_type: str, node_id: str, facility_id: str, field: str) -> None:
    model = NODE_MODELS.get(node_type)
    if model is None:
        raise HTTPException(status_code=422, detail={
            "error": "INVALID_NODE_TYPE", "field": field,
            "message": f"Node type '{node_type}' is not a pipe end-point type (PUMP, TANK, VALVE)."})
    obj = db.get(model, node_id)
    if obj is None:
        raise HTTPException(status_code=422, detail={
            "error": "MISSING_NODE", "field": field,
            "message": f"Pipe references {node_type} '{node_id}', which does not exist. "
                       "A pipe must connect two existing equipment nodes."})
    if obj.facility_id != facility_id:
        raise HTTPException(status_code=422, detail={
            "error": "CROSS_FACILITY_CONNECTION", "field": field,
            "message": f"{node_type} '{node_id}' belongs to {obj.facility_id}, not {facility_id}."})


def validate_pipe(db: Session, data: dict, pipe_id: str | None = None) -> None:
    require_facility(db, data["facility_id"])
    check_node(db, data["from_node_type"], data["from_node_id"], data["facility_id"], "from_node_id")
    check_node(db, data["to_node_type"], data["to_node_id"], data["facility_id"], "to_node_id")
    if data["from_node_id"] == data["to_node_id"]:
        raise HTTPException(status_code=422, detail={
            "error": "SELF_LOOP", "message": "A pipe cannot start and end at the same node."})
    dup = db.query(Pipe).filter(Pipe.from_node_id == data["from_node_id"], Pipe.to_node_id == data["to_node_id"])
    if pipe_id:
        dup = dup.filter(Pipe.id != pipe_id)
    if dup.first():
        raise HTTPException(status_code=409, detail={
            "error": "DUPLICATE_CONNECTION",
            "message": f"A pipe from {data['from_node_id']} to {data['to_node_id']} already exists."})


def validate_sensor(db: Session, data: dict) -> None:
    require_facility(db, data["facility_id"])
    et = data["equipment_type"]
    model = SENSOR_TARGETS.get(et)
    if model is None:
        raise HTTPException(status_code=422, detail={"error": "INVALID_EQUIPMENT_TYPE",
                                                     "message": f"Unknown equipment type '{et}'."})
    obj = db.get(model, data["equipment_id"])
    if obj is None:
        raise HTTPException(status_code=422, detail={
            "error": "MISSING_EQUIPMENT", "field": "equipment_id",
            "message": f"Sensor references {et} '{data['equipment_id']}', which does not exist."})
    if obj.facility_id != data["facility_id"]:
        raise HTTPException(status_code=422, detail={
            "error": "CROSS_FACILITY_REFERENCE",
            "message": f"{et} '{data['equipment_id']}' belongs to {obj.facility_id}, not {data['facility_id']}."})
    if et not in SENSOR_RULES.get(data["sensor_type"], set()):
        raise HTTPException(status_code=422, detail={
            "error": "INVALID_SENSOR_PLACEMENT",
            "message": f"A {data['sensor_type']} sensor cannot be mounted on a {et}."})


def equipment_in_use(db: Session, equipment_id: str) -> list[str]:
    """Pipes and sensors that reference a node (blocks deletion)."""
    refs = [p.id for p in db.query(Pipe).filter((Pipe.from_node_id == equipment_id) | (Pipe.to_node_id == equipment_id))]
    refs += [s.id for s in db.query(Sensor).filter(Sensor.equipment_id == equipment_id)]
    return refs
