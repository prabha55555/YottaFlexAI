from app.models.master import (  # noqa: F401
    Facility,
    OperatingMode,
    Pipe,
    Pump,
    Sensor,
    Tank,
    Telemetry,
    Valve,
)
from app.models.operations import Alarm, AlarmEvent, Anomaly, SimulationRun  # noqa: F401

EQUIPMENT_MODELS = {"PUMP": Pump, "TANK": Tank, "VALVE": Valve, "PIPE": Pipe, "SENSOR": Sensor}
