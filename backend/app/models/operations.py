"""Operational entities: anomalies, alarms (+ history), simulation runs."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, CheckConstraint, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.master import _now

SEVERITIES = ("LOW", "MEDIUM", "HIGH", "CRITICAL")
ALARM_STATUSES = ("ACTIVE", "ACKNOWLEDGED", "RESOLVED", "CLOSED")


class SimulationRun(Base):
    __tablename__ = "simulation_runs"

    id: Mapped[str] = mapped_column(String(24), primary_key=True)  # SIM-2026-000001
    facility_id: Mapped[str] = mapped_column(ForeignKey("facilities.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(160), default="")
    scenario: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)  # COMPLETED / FAILED
    seed: Mapped[int] = mapped_column(Integer, nullable=False)
    steps: Mapped[int] = mapped_column(Integer, nullable=False)
    step_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    start_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    baseline_simulation_id: Mapped[str | None] = mapped_column(
        ForeignKey("simulation_runs.id", ondelete="SET NULL"), nullable=True
    )
    original_config: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    modified_parameters: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    effective_config: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    input_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    summary: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    mass_balance: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    timeseries: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    readings: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    assumptions: Mapped[list | None] = mapped_column(JSON, nullable=True)
    validation_errors: Mapped[list | None] = mapped_column(JSON, nullable=True)
    duration_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)

    __table_args__ = (
        CheckConstraint("status IN ('COMPLETED','FAILED')", name="ck_sim_status"),
        CheckConstraint("steps > 0 AND step_minutes > 0", name="ck_sim_steps"),
    )


class Anomaly(Base):
    __tablename__ = "anomalies"

    id: Mapped[str] = mapped_column(String(24), primary_key=True)  # ANM-000001
    fingerprint: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    facility_id: Mapped[str] = mapped_column(ForeignKey("facilities.id", ondelete="CASCADE"), index=True)
    equipment_type: Mapped[str] = mapped_column(String(10), nullable=False)
    equipment_id: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    sensor_id: Mapped[str | None] = mapped_column(String(20), nullable=True)
    anomaly_type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(15), nullable=False)  # PROCESS / SENSOR / OPERATIONAL
    severity: Mapped[str] = mapped_column(String(10), nullable=False)
    detection_rule: Mapped[str] = mapped_column(String(60), nullable=False)
    rule_description: Mapped[str] = mapped_column(Text, default="")
    start_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    end_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    detected_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    observed_value: Mapped[float | None] = mapped_column(Float)
    expected_value: Mapped[float | None] = mapped_column(Float)
    threshold: Mapped[float | None] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(16), default="")
    evidence: Mapped[dict | None] = mapped_column(JSON)
    recommended_action: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(20), nullable=False)  # TELEMETRY_SCAN / SIMULATION
    simulation_id: Mapped[str | None] = mapped_column(
        ForeignKey("simulation_runs.id", ondelete="CASCADE"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    __table_args__ = (
        CheckConstraint(f"severity IN {SEVERITIES}", name="ck_anomaly_severity"),
        CheckConstraint("category IN ('PROCESS','SENSOR','OPERATIONAL')", name="ck_anomaly_category"),
        Index("ix_anomaly_fac_type", "facility_id", "anomaly_type"),
    )


class Alarm(Base):
    __tablename__ = "alarms"

    id: Mapped[str] = mapped_column(String(24), primary_key=True)  # ALM-000001
    facility_id: Mapped[str] = mapped_column(ForeignKey("facilities.id", ondelete="CASCADE"), index=True)
    equipment_type: Mapped[str] = mapped_column(String(10), nullable=False)
    equipment_id: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    anomaly_id: Mapped[str | None] = mapped_column(
        ForeignKey("anomalies.id", ondelete="SET NULL"), nullable=True, unique=True
    )
    simulation_id: Mapped[str | None] = mapped_column(
        ForeignKey("simulation_runs.id", ondelete="CASCADE"), nullable=True, index=True
    )
    alarm_type: Mapped[str] = mapped_column(String(30), nullable=False)
    severity: Mapped[str] = mapped_column(String(10), nullable=False)
    status: Mapped[str] = mapped_column(String(15), nullable=False, default="ACTIVE", index=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    recommended_action: Mapped[str] = mapped_column(Text, default="")
    raised_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime)
    acknowledged_by: Mapped[str | None] = mapped_column(String(60))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime)
    resolved_by: Mapped[str | None] = mapped_column(String(60))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime)
    closed_by: Mapped[str | None] = mapped_column(String(60))

    events: Mapped[list["AlarmEvent"]] = relationship(
        back_populates="alarm", cascade="all, delete-orphan", order_by="AlarmEvent.id"
    )

    __table_args__ = (
        CheckConstraint(f"severity IN {SEVERITIES}", name="ck_alarm_severity"),
        CheckConstraint(f"status IN {ALARM_STATUSES}", name="ck_alarm_status"),
    )


class AlarmEvent(Base):
    """Immutable audit record of every alarm status change."""

    __tablename__ = "alarm_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    alarm_id: Mapped[str] = mapped_column(ForeignKey("alarms.id", ondelete="CASCADE"), index=True)
    from_status: Mapped[str | None] = mapped_column(String(15))
    to_status: Mapped[str] = mapped_column(String(15), nullable=False)
    actor: Mapped[str] = mapped_column(String(60), nullable=False, default="system")
    note: Mapped[str] = mapped_column(Text, default="")
    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now)

    alarm: Mapped[Alarm] = relationship(back_populates="events")
