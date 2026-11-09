"""Request/response schemas for master data and equipment."""
from __future__ import annotations

from datetime import datetime
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    skip: int
    limit: int


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------- facility
class FacilityBase(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    location: str = Field(default="", max_length=120)
    description: str = ""
    status: Literal["OPERATIONAL", "MAINTENANCE", "SHUTDOWN"] = "OPERATIONAL"
    operating_mode_id: str | None = None


class FacilityCreate(FacilityBase):
    pass


class FacilityUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    location: str | None = None
    description: str | None = None
    status: Literal["OPERATIONAL", "MAINTENANCE", "SHUTDOWN"] | None = None
    operating_mode_id: str | None = None


class FacilityRead(FacilityBase, ORM):
    id: str
    created_at: datetime | None = None


class OperatingModeBase(BaseModel):
    name: str = Field(min_length=2, max_length=50)
    description: str = ""
    demand_factor: float = Field(1.0, ge=0, le=3)
    pump_speed_factor: float = Field(1.0, gt=0, le=1.2)


class OperatingModeRead(OperatingModeBase, ORM):
    id: str


# -------------------------------------------------------------------- pump
class PumpBase(BaseModel):
    facility_id: str
    name: str = Field(min_length=2, max_length=120)
    rated_flow_m3h: float = Field(gt=0, le=5000)
    shutoff_head_m: float = Field(gt=0, le=500)
    curve_k: float = Field(gt=0)
    speed_pct: float = Field(100.0, ge=0, le=110)
    rated_power_kw: float = Field(30.0, gt=0)
    best_efficiency: float = Field(0.75, gt=0, le=1)
    health_factor: float = Field(1.0, gt=0, le=1)
    available: bool = True
    status: Literal["RUNNING", "STOPPED", "MAINTENANCE", "TRIPPED"] = "RUNNING"


class PumpCreate(PumpBase):
    pass


class PumpUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    rated_flow_m3h: float | None = Field(default=None, gt=0, le=5000)
    shutoff_head_m: float | None = Field(default=None, gt=0, le=500)
    curve_k: float | None = Field(default=None, gt=0)
    speed_pct: float | None = Field(default=None, ge=0, le=110)
    rated_power_kw: float | None = Field(default=None, gt=0)
    best_efficiency: float | None = Field(default=None, gt=0, le=1)
    health_factor: float | None = Field(default=None, gt=0, le=1)
    available: bool | None = None
    status: Literal["RUNNING", "STOPPED", "MAINTENANCE", "TRIPPED"] | None = None


class PumpRead(PumpBase, ORM):
    id: str


# -------------------------------------------------------------------- tank
class TankBase(BaseModel):
    facility_id: str
    name: str = Field(min_length=2, max_length=120)
    capacity_m3: float = Field(gt=0, le=1_000_000)
    height_m: float = Field(gt=0, le=100)
    elevation_m: float = Field(0.0, ge=-50, le=500)
    initial_level_pct: float = Field(50.0, ge=0, le=100)
    setpoint_pct: float = Field(50.0, ge=0, le=100)
    high_alarm_pct: float = Field(95.0, gt=0, le=100)
    low_alarm_pct: float = Field(10.0, ge=0, lt=100)
    status: Literal["IN_SERVICE", "OUT_OF_SERVICE"] = "IN_SERVICE"

    @model_validator(mode="after")
    def _alarm_band(self):
        if self.low_alarm_pct >= self.high_alarm_pct:
            raise ValueError("low_alarm_pct must be below high_alarm_pct")
        return self


class TankCreate(TankBase):
    pass


class TankUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    capacity_m3: float | None = Field(default=None, gt=0, le=1_000_000)
    height_m: float | None = Field(default=None, gt=0, le=100)
    elevation_m: float | None = Field(default=None, ge=-50, le=500)
    initial_level_pct: float | None = Field(default=None, ge=0, le=100)
    setpoint_pct: float | None = Field(default=None, ge=0, le=100)
    high_alarm_pct: float | None = Field(default=None, gt=0, le=100)
    low_alarm_pct: float | None = Field(default=None, ge=0, lt=100)
    status: Literal["IN_SERVICE", "OUT_OF_SERVICE"] | None = None


class TankRead(TankBase, ORM):
    id: str


# ------------------------------------------------------------------- valve
ValveType = Literal["GATE", "GLOBE", "BUTTERFLY", "BALL", "CONTROL", "CHECK"]
ValveRole = Literal["INLINE", "INLET", "OUTLET"]


class ValveBase(BaseModel):
    facility_id: str
    name: str = Field(min_length=2, max_length=120)
    valve_type: ValveType = "GATE"
    role: ValveRole = "INLINE"
    opening_pct: float = Field(100.0, ge=0, le=100)
    resistance_full_open: float = Field(1e-4, gt=0)
    boundary_flow_m3h: float | None = Field(default=None, ge=0)
    status: Literal["IN_SERVICE", "OUT_OF_SERVICE"] = "IN_SERVICE"


class ValveCreate(ValveBase):
    pass


class ValveUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    valve_type: ValveType | None = None
    role: ValveRole | None = None
    opening_pct: float | None = Field(default=None, ge=0, le=100)
    resistance_full_open: float | None = Field(default=None, gt=0)
    boundary_flow_m3h: float | None = Field(default=None, ge=0)
    status: Literal["IN_SERVICE", "OUT_OF_SERVICE"] | None = None


class ValveRead(ValveBase, ORM):
    id: str


# -------------------------------------------------------------------- pipe
NodeType = Literal["PUMP", "TANK", "VALVE"]


class PipeBase(BaseModel):
    facility_id: str
    name: str = Field(min_length=2, max_length=120)
    from_node_type: NodeType
    from_node_id: str
    to_node_type: NodeType
    to_node_id: str
    length_m: float = Field(gt=0, le=100_000)
    diameter_mm: float = Field(gt=0, le=3000)
    friction_factor: float = Field(0.02, gt=0, lt=0.2)
    max_flow_m3h: float = Field(gt=0)
    max_pressure_bar: float = Field(10.0, gt=0, le=250)
    restriction_pct: float = Field(0.0, ge=0, lt=100)
    status: Literal["IN_SERVICE", "OUT_OF_SERVICE"] = "IN_SERVICE"


class PipeCreate(PipeBase):
    pass


class PipeUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    from_node_type: NodeType | None = None
    from_node_id: str | None = None
    to_node_type: NodeType | None = None
    to_node_id: str | None = None
    length_m: float | None = Field(default=None, gt=0, le=100_000)
    diameter_mm: float | None = Field(default=None, gt=0, le=3000)
    friction_factor: float | None = Field(default=None, gt=0, lt=0.2)
    max_flow_m3h: float | None = Field(default=None, gt=0)
    max_pressure_bar: float | None = Field(default=None, gt=0, le=250)
    restriction_pct: float | None = Field(default=None, ge=0, lt=100)
    status: Literal["IN_SERVICE", "OUT_OF_SERVICE"] | None = None


class PipeRead(PipeBase, ORM):
    id: str


# ------------------------------------------------------------------ sensor
class SensorBase(BaseModel):
    facility_id: str
    name: str = Field(min_length=2, max_length=120)
    tag: str = Field(min_length=2, max_length=40)
    equipment_type: Literal["PUMP", "TANK", "VALVE", "PIPE"]
    equipment_id: str
    sensor_type: Literal["FLOW", "PRESSURE", "LEVEL"]
    measurement_point: str = Field(min_length=2, max_length=20)
    unit: str = Field(min_length=1, max_length=10)
    min_range: float
    max_range: float
    accuracy_pct: float = Field(0.5, gt=0, le=10)
    status: Literal["ACTIVE", "INACTIVE", "FAULTY"] = "ACTIVE"

    @model_validator(mode="after")
    def _range(self):
        if self.min_range >= self.max_range:
            raise ValueError("min_range must be below max_range")
        return self


class SensorCreate(SensorBase):
    pass


class SensorUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    tag: str | None = Field(default=None, min_length=2, max_length=40)
    equipment_type: Literal["PUMP", "TANK", "VALVE", "PIPE"] | None = None
    equipment_id: str | None = None
    sensor_type: Literal["FLOW", "PRESSURE", "LEVEL"] | None = None
    measurement_point: str | None = None
    unit: str | None = None
    min_range: float | None = None
    max_range: float | None = None
    accuracy_pct: float | None = Field(default=None, gt=0, le=10)
    status: Literal["ACTIVE", "INACTIVE", "FAULTY"] | None = None


class SensorRead(SensorBase, ORM):
    id: str
