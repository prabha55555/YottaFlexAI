"""Schemas for telemetry, anomalies, alarms and simulations."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.config import DEFAULT_SEED


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class TelemetryRead(ORM):
    id: int
    sensor_id: str
    timestamp: datetime
    value: float | None
    derived_value: float | None
    derived_unit: str | None
    source: str


class AnomalyRead(ORM):
    id: str
    facility_id: str
    equipment_type: str
    equipment_id: str
    sensor_id: str | None
    anomaly_type: str
    category: str
    severity: str
    detection_rule: str
    rule_description: str
    start_time: datetime
    end_time: datetime
    detected_at: datetime
    observed_value: float | None
    expected_value: float | None
    threshold: float | None
    unit: str
    evidence: dict | None
    recommended_action: str
    source: str
    simulation_id: str | None


class AlarmEventRead(ORM):
    id: int
    from_status: str | None
    to_status: str
    actor: str
    note: str
    timestamp: datetime


class AlarmRead(ORM):
    id: str
    facility_id: str
    equipment_type: str
    equipment_id: str
    anomaly_id: str | None
    simulation_id: str | None
    alarm_type: str
    severity: str
    status: str
    message: str
    recommended_action: str
    raised_at: datetime
    acknowledged_at: datetime | None
    acknowledged_by: str | None
    resolved_at: datetime | None
    resolved_by: str | None
    closed_at: datetime | None
    closed_by: str | None


class AlarmDetail(AlarmRead):
    events: list[AlarmEventRead]
    anomaly: AnomalyRead | None = None


class AlarmAction(BaseModel):
    actor: str = Field("operator", min_length=1, max_length=60)
    note: str = Field("", max_length=500)


class SimulationParameters(BaseModel):
    operating_mode_id: str | None = None
    demand_factor: float | None = None
    pump_speeds: dict[str, float] | None = None
    pump_availability: dict[str, bool] | None = None
    valve_openings: dict[str, float] | None = None
    tank_initial_levels: dict[str, float] | None = None
    flow_demand: dict[str, float] | None = None
    pipe_restrictions: dict[str, float] | None = None
    pipe_leaks: dict[str, float] | None = None
    pump_health: dict[str, float] | None = None
    sensor_faults: dict[str, str] | None = None


class SimulationRequest(BaseModel):
    facility_id: str
    scenario: Literal["NORMAL", "LEAKAGE", "BLOCKAGE", "PUMP_DEGRADATION", "SENSOR_MALFUNCTION", "HIGH_DEMAND",
                      "VALVE_CLOSURE", "TANK_OVERCAPACITY"] | str
    name: str = Field("", max_length=160)
    seed: int = DEFAULT_SEED
    steps: int = 96
    step_minutes: int = 15
    fault_start_step: int | None = None
    parameters: SimulationParameters = Field(default_factory=SimulationParameters)
    apply_preset: bool = True
    run_baseline: bool = True
    baseline_simulation_id: str | None = None


class SimulationListItem(ORM):
    id: str
    facility_id: str
    name: str
    scenario: str
    status: str
    seed: int
    steps: int
    step_minutes: int
    baseline_simulation_id: str | None
    input_hash: str | None
    duration_ms: float | None
    created_at: datetime
    summary: dict | None
    validation_errors: list | None


class SimulationDetail(SimulationListItem):
    start_time: datetime
    original_config: dict | None
    modified_parameters: dict | None
    effective_config: dict | None
    mass_balance: dict | None
    timeseries: dict | None
    assumptions: list | None


class Message(BaseModel):
    message: str
    data: Any = None
