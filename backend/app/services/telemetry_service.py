"""Telemetry queries: history, time-range filtering, wide-format loading for analysis."""
from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Sensor, Telemetry


def time_bounds(db: Session, facility_id: str | None = None) -> tuple[datetime | None, datetime | None]:
    q = select(func.min(Telemetry.timestamp), func.max(Telemetry.timestamp))
    if facility_id:
        q = q.join(Sensor, Sensor.id == Telemetry.sensor_id).where(Sensor.facility_id == facility_id)
    return db.execute(q).one()


def infer_step_minutes(timestamps: list[datetime]) -> int:
    if len(timestamps) < 2:
        return 15
    diffs = np.diff(np.array(timestamps, dtype="datetime64[s]")).astype(int)
    return max(int(np.median(diffs) // 60), 1)


def load_wide(db: Session, facility_id: str, start: datetime | None = None, end: datetime | None = None,
              sensor_ids: list[str] | None = None) -> tuple[list[datetime], dict[str, np.ndarray]]:
    """Return (timestamps, {sensor_id: values}) on a regular grid; absent rows -> NaN."""
    q = (select(Telemetry.sensor_id, Telemetry.timestamp, Telemetry.value)
         .join(Sensor, Sensor.id == Telemetry.sensor_id)
         .where(Sensor.facility_id == facility_id))
    if start:
        q = q.where(Telemetry.timestamp >= start)
    if end:
        q = q.where(Telemetry.timestamp <= end)
    if sensor_ids:
        q = q.where(Telemetry.sensor_id.in_(sensor_ids))
    rows = db.execute(q).all()
    if not rows:
        return [], {}
    df = pd.DataFrame(rows, columns=["sensor_id", "timestamp", "value"])
    wide = df.pivot_table(index="timestamp", columns="sensor_id", values="value", aggfunc="first", dropna=False)
    ts = list(pd.to_datetime(wide.index).to_pydatetime())
    step = infer_step_minutes(ts)
    full_idx = pd.date_range(ts[0], ts[-1], freq=f"{step}min")
    wide = wide.reindex(full_idx)  # missing timestamps become NaN (missing readings)
    timestamps = list(full_idx.to_pydatetime())
    return timestamps, {c: wide[c].to_numpy(dtype=float) for c in wide.columns}


def resample_series(timestamps: list[datetime], values: np.ndarray, max_points: int) -> tuple[list, list]:
    """Bucket-average to at most ``max_points`` points for charting."""
    n = len(timestamps)
    if n <= max_points:
        return timestamps, [None if np.isnan(v) else float(v) for v in values]
    size = int(np.ceil(n / max_points))
    out_t, out_v = [], []
    for i in range(0, n, size):
        seg = values[i:i + size]
        out_t.append(timestamps[i])
        out_v.append(None if np.isnan(seg).all() else float(np.nanmean(seg)))
    return out_t, out_v
