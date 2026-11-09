"""CRUD endpoints for facilities, operating modes and equipment."""

from collections.abc import Callable

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Alarm, Facility, OperatingMode, Pipe, Pump, Sensor, Tank, Telemetry, Valve
from app.schemas.equipment import (
    FacilityCreate, FacilityRead, FacilityUpdate, OperatingModeBase, OperatingModeRead, Page,
    PipeCreate, PipeRead, PipeUpdate, PumpCreate, PumpRead, PumpUpdate, SensorCreate, SensorRead, SensorUpdate,
    TankCreate, TankRead, TankUpdate, ValveCreate, ValveRead, ValveUpdate,
)
from app.services import references as refs
from app.services.ids import next_id

router = APIRouter()


def _commit(db: Session):
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail={"error": "INTEGRITY_ERROR",
                                                     "message": str(exc.orig).split("\n")[0]}) from exc


# ------------------------------------------------------------------ facilities
@router.get("/facilities", response_model=list[FacilityRead], tags=["facilities"])
def list_facilities(db: Session = Depends(get_db)):
    return db.scalars(select(Facility).order_by(Facility.id)).all()


@router.get("/facilities/{facility_id}", response_model=FacilityRead, tags=["facilities"])
def get_facility(facility_id: str, db: Session = Depends(get_db)):
    fac = db.get(Facility, facility_id)
    if not fac:
        raise HTTPException(404, f"Facility {facility_id} not found")
    return fac


@router.get("/facilities/{facility_id}/summary", tags=["facilities"])
def facility_summary(facility_id: str, db: Session = Depends(get_db)):
    fac = get_facility(facility_id, db)
    counts = {}
    for name, model in (("pumps", Pump), ("tanks", Tank), ("valves", Valve), ("pipes", Pipe), ("sensors", Sensor)):
        counts[name] = db.scalar(select(func.count(model.id)).where(model.facility_id == facility_id))
    tel = db.scalar(select(func.count(Telemetry.id)).join(Sensor, Sensor.id == Telemetry.sensor_id)
                    .where(Sensor.facility_id == facility_id))
    active = db.execute(select(Alarm.severity, func.count(Alarm.id))
                        .where(Alarm.facility_id == facility_id, Alarm.simulation_id.is_(None),
                               Alarm.status.in_(("ACTIVE", "ACKNOWLEDGED"))).group_by(Alarm.severity)).all()
    cap = db.scalar(select(func.sum(Tank.capacity_m3)).where(Tank.facility_id == facility_id)) or 0
    flow = db.scalar(select(func.sum(Pump.rated_flow_m3h)).where(Pump.facility_id == facility_id)) or 0
    return {"facility": FacilityRead.model_validate(fac), "counts": counts, "telemetry_records": tel,
            "active_alarms_by_severity": dict(active), "total_storage_m3": cap, "installed_pump_flow_m3h": flow,
            "operating_mode": fac.operating_mode.name if fac.operating_mode else None}


@router.post("/facilities", response_model=FacilityRead, status_code=201, tags=["facilities"])
def create_facility(body: FacilityCreate, db: Session = Depends(get_db)):
    if body.operating_mode_id and not db.get(OperatingMode, body.operating_mode_id):
        raise HTTPException(422, {"error": "FOREIGN_KEY_VIOLATION",
                                  "message": f"Operating mode {body.operating_mode_id} does not exist."})
    if db.scalar(select(Facility).where(Facility.name == body.name)):
        raise HTTPException(409, {"error": "DUPLICATE_NAME", "message": f"Facility '{body.name}' already exists."})
    fac = Facility(id=next_id(db, Facility.id, "FAC"), **body.model_dump())
    db.add(fac)
    _commit(db)
    return fac


@router.put("/facilities/{facility_id}", response_model=FacilityRead, tags=["facilities"])
def update_facility(facility_id: str, body: FacilityUpdate, db: Session = Depends(get_db)):
    fac = get_facility(facility_id, db)
    data = body.model_dump(exclude_unset=True)
    if data.get("operating_mode_id") and not db.get(OperatingMode, data["operating_mode_id"]):
        raise HTTPException(422, {"error": "FOREIGN_KEY_VIOLATION",
                                  "message": f"Operating mode {data['operating_mode_id']} does not exist."})
    for k, v in data.items():
        setattr(fac, k, v)
    _commit(db)
    return fac


@router.delete("/facilities/{facility_id}", status_code=204, tags=["facilities"])
def delete_facility(facility_id: str, force: bool = False, db: Session = Depends(get_db)):
    fac = get_facility(facility_id, db)
    n_eq = sum(db.scalar(select(func.count(m.id)).where(m.facility_id == facility_id)) for m in (Pump, Tank, Valve))
    if n_eq and not force:
        raise HTTPException(409, {"error": "FACILITY_NOT_EMPTY",
                                  "message": f"{facility_id} still has {n_eq} equipment item(s). "
                                             "Delete them first or pass force=true."})
    db.delete(fac)
    _commit(db)
    return Response(status_code=204)


# ------------------------------------------------------------- operating modes
@router.get("/operating-modes", response_model=list[OperatingModeRead], tags=["facilities"])
def list_modes(db: Session = Depends(get_db)):
    return db.scalars(select(OperatingMode).order_by(OperatingMode.id)).all()


@router.post("/operating-modes", response_model=OperatingModeRead, status_code=201, tags=["facilities"])
def create_mode(body: OperatingModeBase, db: Session = Depends(get_db)):
    m = OperatingMode(id=next_id(db, OperatingMode.id, "MODE"), **body.model_dump())
    db.add(m)
    _commit(db)
    return m


# --------------------------------------------------------- generic equipment
def crud_router(model, path: str, id_prefix: str, create_s, update_s, read_s,
                validate: Callable[[Session, dict, str | None], None] | None, search_fields: tuple[str, ...],
                tag: str, filter_fields: tuple[str, ...] = ()) -> APIRouter:
    r = APIRouter(tags=[tag])

    @r.get(f"/{path}", response_model=Page[read_s], name=f"list_{path}")
    def list_items(facility_id: str | None = None, q: str | None = None,
                   skip: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=1000),
                   filter_value: str | None = Query(None, alias="filter"), db: Session = Depends(get_db)):
        stmt = select(model)
        if facility_id:
            stmt = stmt.where(model.facility_id == facility_id)
        if q:
            stmt = stmt.where(or_(*[getattr(model, f).ilike(f"%{q}%") for f in search_fields]))
        if filter_value and filter_fields:
            stmt = stmt.where(or_(*[getattr(model, f) == filter_value for f in filter_fields]))
        total = db.scalar(select(func.count()).select_from(stmt.subquery()))
        items = db.scalars(stmt.order_by(model.id).offset(skip).limit(limit)).all()
        return {"items": items, "total": total, "skip": skip, "limit": limit}

    @r.get(f"/{path}/{{item_id}}", response_model=read_s, name=f"get_{path}")
    def get_item(item_id: str, db: Session = Depends(get_db)):
        obj = db.get(model, item_id)
        if not obj:
            raise HTTPException(404, f"{id_prefix} {item_id} not found")
        return obj

    @r.post(f"/{path}", response_model=read_s, status_code=status.HTTP_201_CREATED, name=f"create_{path}")
    def create_item(body: create_s, db: Session = Depends(get_db)):
        data = body.model_dump()
        refs.require_facility(db, data["facility_id"])
        if validate:
            validate(db, data, None)
        obj = model(id=next_id(db, model.id, id_prefix), **data)
        db.add(obj)
        _commit(db)
        return obj

    @r.put(f"/{path}/{{item_id}}", response_model=read_s, name=f"update_{path}")
    def update_item(item_id: str, body: update_s, db: Session = Depends(get_db)):
        obj = get_item(item_id, db)
        data = body.model_dump(exclude_unset=True)
        merged = {c.name: getattr(obj, c.name) for c in model.__table__.columns}
        merged.update(data)
        if validate:
            validate(db, merged, item_id)
        for k, v in data.items():
            setattr(obj, k, v)
        _commit(db)
        return obj

    @r.delete(f"/{path}/{{item_id}}", status_code=204, name=f"delete_{path}")
    def delete_item(item_id: str, db: Session = Depends(get_db)):
        obj = get_item(item_id, db)
        if model in (Pump, Tank, Valve, Pipe):
            used = refs.equipment_in_use(db, item_id)
            if used:
                raise HTTPException(409, {"error": "IN_USE",
                                          "message": f"{item_id} is referenced by {', '.join(used[:8])}"
                                                     f"{'...' if len(used) > 8 else ''}. Remove those first."})
        db.delete(obj)
        _commit(db)
        return Response(status_code=204)

    return r


def _validate_pipe(db, data, pid):
    refs.validate_pipe(db, data, pid)


def _validate_sensor(db, data, sid):
    refs.validate_sensor(db, data)
    dup = db.scalar(select(Sensor).where(Sensor.facility_id == data["facility_id"], Sensor.tag == data["tag"],
                                         Sensor.id != (sid or "")))
    if dup:
        raise HTTPException(409, {"error": "DUPLICATE_TAG", "message": f"Tag {data['tag']} already used by {dup.id}."})
    if data["min_range"] >= data["max_range"]:
        raise HTTPException(422, {"error": "INVALID_RANGE", "message": "min_range must be below max_range."})


def _validate_tank(db, data, tid):
    if data["low_alarm_pct"] >= data["high_alarm_pct"]:
        raise HTTPException(422, {"error": "INVALID_ALARM_BAND", "message": "low_alarm_pct must be below high_alarm_pct."})
    if not 0 <= data["initial_level_pct"] <= 100:
        raise HTTPException(422, {"error": "LEVEL_EXCEEDS_CAPACITY",
                                  "message": "initial_level_pct must be within 0-100 % of capacity."})


router.include_router(crud_router(Pump, "pumps", "PUMP", PumpCreate, PumpUpdate, PumpRead, None,
                                  ("id", "name"), "pumps", ("status",)))
router.include_router(crud_router(Tank, "tanks", "TANK", TankCreate, TankUpdate, TankRead, _validate_tank,
                                  ("id", "name"), "tanks", ("status",)))
router.include_router(crud_router(Valve, "valves", "VALVE", ValveCreate, ValveUpdate, ValveRead, None,
                                  ("id", "name"), "valves", ("role", "valve_type")))
router.include_router(crud_router(Pipe, "pipes", "PIPE", PipeCreate, PipeUpdate, PipeRead, _validate_pipe,
                                  ("id", "name", "from_node_id", "to_node_id"), "pipes", ("status",)))
router.include_router(crud_router(Sensor, "sensors", "SNS", SensorCreate, SensorUpdate, SensorRead,
                                  _validate_sensor, ("id", "name", "tag", "equipment_id"), "sensors",
                                  ("sensor_type",)))
