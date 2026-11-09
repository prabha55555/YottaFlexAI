"""Master data and equipment entities.

Polymorphic equipment references (pipe end-points, sensor mount points) cannot be
expressed as a single SQL foreign key because the target table depends on the
node type. They are therefore enforced at the service layer (see
``app.services.references``) and re-checked by the integrity validator
(``app.validation.integrity``). All other relationships use real foreign keys
with ``PRAGMA foreign_keys=ON``.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)


class OperatingMode(Base):
    __tablename__ = "operating_modes"

    id: Mapped[str] = mapped_column(String(20), primary_key=True)  # MODE-001
    name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    demand_factor: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    pump_speed_factor: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)

    __table_args__ = (
        CheckConstraint("demand_factor >= 0 AND demand_factor <= 3", name="ck_mode_demand"),
        CheckConstraint("pump_speed_factor > 0 AND pump_speed_factor <= 1.2", name="ck_mode_speed"),
    )


class Facility(Base):
    __tablename__ = "facilities"

    id: Mapped[str] = mapped_column(String(20), primary_key=True)  # FAC-001
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    location: Mapped[str] = mapped_column(String(120), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="OPERATIONAL")
    operating_mode_id: Mapped[str | None] = mapped_column(
        ForeignKey("operating_modes.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    operating_mode: Mapped[OperatingMode | None] = relationship()
    pumps: Mapped[list["Pump"]] = relationship(back_populates="facility", cascade="all, delete-orphan")
    tanks: Mapped[list["Tank"]] = relationship(back_populates="facility", cascade="all, delete-orphan")
    valves: Mapped[list["Valve"]] = relationship(back_populates="facility", cascade="all, delete-orphan")
    pipes: Mapped[list["Pipe"]] = relationship(back_populates="facility", cascade="all, delete-orphan")
    sensors: Mapped[list["Sensor"]] = relationship(back_populates="facility", cascade="all, delete-orphan")

    __table_args__ = (
        CheckConstraint(
            "status IN ('OPERATIONAL','MAINTENANCE','SHUTDOWN')", name="ck_facility_status"
        ),
    )


class Pump(Base):
    """Centrifugal pump with simplified curve H(Q) = s^2*H0 - k*Q^2 (s = speed ratio)."""

    __tablename__ = "pumps"

    id: Mapped[str] = mapped_column(String(20), primary_key=True)  # PUMP-001
    facility_id: Mapped[str] = mapped_column(
        ForeignKey("facilities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    rated_flow_m3h: Mapped[float] = mapped_column(Float, nullable=False)
    shutoff_head_m: Mapped[float] = mapped_column(Float, nullable=False)  # H0 at 100% speed
    curve_k: Mapped[float] = mapped_column(Float, nullable=False)  # m / (m3/h)^2
    speed_pct: Mapped[float] = mapped_column(Float, nullable=False, default=100.0)
    rated_power_kw: Mapped[float] = mapped_column(Float, nullable=False, default=30.0)
    best_efficiency: Mapped[float] = mapped_column(Float, nullable=False, default=0.75)
    health_factor: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    available: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="RUNNING")

    facility: Mapped[Facility] = relationship(back_populates="pumps")

    __table_args__ = (
        CheckConstraint("rated_flow_m3h > 0", name="ck_pump_rated_flow"),
        CheckConstraint("shutoff_head_m > 0", name="ck_pump_h0"),
        CheckConstraint("curve_k > 0", name="ck_pump_k"),
        CheckConstraint("speed_pct >= 0 AND speed_pct <= 110", name="ck_pump_speed"),
        CheckConstraint("health_factor > 0 AND health_factor <= 1", name="ck_pump_health"),
        CheckConstraint("best_efficiency > 0 AND best_efficiency <= 1", name="ck_pump_eff"),
        CheckConstraint("status IN ('RUNNING','STOPPED','MAINTENANCE','TRIPPED')", name="ck_pump_status"),
    )


class Tank(Base):
    __tablename__ = "tanks"

    id: Mapped[str] = mapped_column(String(20), primary_key=True)  # TANK-001
    facility_id: Mapped[str] = mapped_column(
        ForeignKey("facilities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    capacity_m3: Mapped[float] = mapped_column(Float, nullable=False)
    height_m: Mapped[float] = mapped_column(Float, nullable=False)
    elevation_m: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    initial_level_pct: Mapped[float] = mapped_column(Float, nullable=False, default=50.0)
    setpoint_pct: Mapped[float] = mapped_column(Float, nullable=False, default=50.0)
    high_alarm_pct: Mapped[float] = mapped_column(Float, nullable=False, default=95.0)
    low_alarm_pct: Mapped[float] = mapped_column(Float, nullable=False, default=10.0)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="IN_SERVICE")

    facility: Mapped[Facility] = relationship(back_populates="tanks")

    __table_args__ = (
        CheckConstraint("capacity_m3 > 0", name="ck_tank_capacity"),
        CheckConstraint("height_m > 0", name="ck_tank_height"),
        CheckConstraint("initial_level_pct >= 0 AND initial_level_pct <= 100", name="ck_tank_level"),
        CheckConstraint("setpoint_pct >= 0 AND setpoint_pct <= 100", name="ck_tank_sp"),
        CheckConstraint("low_alarm_pct < high_alarm_pct", name="ck_tank_alarm_band"),
        CheckConstraint("high_alarm_pct <= 100", name="ck_tank_high"),
        CheckConstraint("status IN ('IN_SERVICE','OUT_OF_SERVICE')", name="ck_tank_status"),
    )


class Valve(Base):
    """Valve. role: INLINE (inside a pump line), INLET (facility supply boundary),
    OUTLET (consumer/demand boundary)."""

    __tablename__ = "valves"

    id: Mapped[str] = mapped_column(String(20), primary_key=True)  # VALVE-001
    facility_id: Mapped[str] = mapped_column(
        ForeignKey("facilities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    valve_type: Mapped[str] = mapped_column(String(20), nullable=False, default="GATE")
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="INLINE")
    opening_pct: Mapped[float] = mapped_column(Float, nullable=False, default=100.0)
    # Loss coefficient at 100% opening, in m/(m3/h)^2. Effective R = R100 / f^2.
    resistance_full_open: Mapped[float] = mapped_column(Float, nullable=False, default=1e-4)
    # Boundary capacity: max supply for INLET valves / nominal demand for OUTLET valves
    boundary_flow_m3h: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="IN_SERVICE")

    facility: Mapped[Facility] = relationship(back_populates="valves")

    __table_args__ = (
        CheckConstraint("opening_pct >= 0 AND opening_pct <= 100", name="ck_valve_opening"),
        CheckConstraint("role IN ('INLINE','INLET','OUTLET')", name="ck_valve_role"),
        CheckConstraint(
            "valve_type IN ('GATE','GLOBE','BUTTERFLY','BALL','CONTROL','CHECK')", name="ck_valve_type"
        ),
        CheckConstraint("resistance_full_open > 0", name="ck_valve_r"),
    )


EQUIPMENT_NODE_TYPES = ("PUMP", "TANK", "VALVE")


class Pipe(Base):
    """Directed pipe segment between two equipment nodes (flow from -> to)."""

    __tablename__ = "pipes"

    id: Mapped[str] = mapped_column(String(20), primary_key=True)  # PIPE-001
    facility_id: Mapped[str] = mapped_column(
        ForeignKey("facilities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    from_node_type: Mapped[str] = mapped_column(String(10), nullable=False)
    from_node_id: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    to_node_type: Mapped[str] = mapped_column(String(10), nullable=False)
    to_node_id: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    length_m: Mapped[float] = mapped_column(Float, nullable=False)
    diameter_mm: Mapped[float] = mapped_column(Float, nullable=False)
    friction_factor: Mapped[float] = mapped_column(Float, nullable=False, default=0.02)
    max_flow_m3h: Mapped[float] = mapped_column(Float, nullable=False)
    max_pressure_bar: Mapped[float] = mapped_column(Float, nullable=False, default=10.0)
    restriction_pct: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="IN_SERVICE")

    facility: Mapped[Facility] = relationship(back_populates="pipes")

    __table_args__ = (
        UniqueConstraint("from_node_id", "to_node_id", name="uq_pipe_endpoints"),
        CheckConstraint("from_node_id <> to_node_id", name="ck_pipe_no_self_loop"),
        CheckConstraint(f"from_node_type IN {EQUIPMENT_NODE_TYPES}", name="ck_pipe_from_type"),
        CheckConstraint(f"to_node_type IN {EQUIPMENT_NODE_TYPES}", name="ck_pipe_to_type"),
        CheckConstraint("length_m > 0 AND diameter_mm > 0", name="ck_pipe_geometry"),
        CheckConstraint("max_flow_m3h > 0 AND max_pressure_bar > 0", name="ck_pipe_limits"),
        CheckConstraint("restriction_pct >= 0 AND restriction_pct < 100", name="ck_pipe_restriction"),
    )


class Sensor(Base):
    __tablename__ = "sensors"

    id: Mapped[str] = mapped_column(String(20), primary_key=True)  # SNS-001
    facility_id: Mapped[str] = mapped_column(
        ForeignKey("facilities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    tag: Mapped[str] = mapped_column(String(40), nullable=False)  # e.g. FT-101
    equipment_type: Mapped[str] = mapped_column(String(10), nullable=False)
    equipment_id: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    sensor_type: Mapped[str] = mapped_column(String(10), nullable=False)
    # Measurement point within the equipment (e.g. DISCHARGE, SUCTION, OUTLET_END, LEVEL)
    measurement_point: Mapped[str] = mapped_column(String(20), nullable=False)
    unit: Mapped[str] = mapped_column(String(10), nullable=False)
    min_range: Mapped[float] = mapped_column(Float, nullable=False)
    max_range: Mapped[float] = mapped_column(Float, nullable=False)
    accuracy_pct: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE")

    facility: Mapped[Facility] = relationship(back_populates="sensors")

    __table_args__ = (
        UniqueConstraint("facility_id", "tag", name="uq_sensor_tag"),
        CheckConstraint("sensor_type IN ('FLOW','PRESSURE','LEVEL')", name="ck_sensor_type"),
        CheckConstraint("equipment_type IN ('PUMP','TANK','VALVE','PIPE')", name="ck_sensor_eq_type"),
        CheckConstraint("min_range < max_range", name="ck_sensor_range"),
        CheckConstraint("status IN ('ACTIVE','INACTIVE','FAULTY')", name="ck_sensor_status"),
        Index("ix_sensor_equipment", "equipment_type", "equipment_id"),
    )


class Telemetry(Base):
    """Simulated sensor reading. ``value`` is NULL when the historian logged the
    timestamp but no value was received (missing reading)."""

    __tablename__ = "telemetry"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sensor_id: Mapped[str] = mapped_column(
        ForeignKey("sensors.id", ondelete="CASCADE"), nullable=False
    )
    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Derived from the raw value: LEVEL -> volume m3, PRESSURE -> head m, FLOW -> m3 per interval
    derived_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    derived_unit: Mapped[str | None] = mapped_column(String(10), nullable=True)
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="SYNTHETIC")

    __table_args__ = (
        UniqueConstraint("sensor_id", "timestamp", name="uq_telemetry_sensor_ts"),
        Index("ix_telemetry_ts", "timestamp"),
    )
