"""Data generation: counts, deterministic IDs, referential validity, reproducibility."""
from __future__ import annotations

import hashlib
import json

import numpy as np
from sqlalchemy import func, inspect, select

from app.config import DEFAULT_SEED
from app.generation.generator import SCALES, export_files, generate_dataset
from app.models import Facility, Pipe, Pump, Sensor, Tank, Telemetry, Valve
from app.services.ids import is_valid_id, next_id, next_simulation_id


def test_full_scale_produces_exactly_100k_telemetry_records():
    ds = generate_dataset(DEFAULT_SEED, "full")
    assert len(ds.telemetry_rows) == 100_000
    counts = {k: len(v) for k, v in ds.master.items()}
    assert counts["facilities"] == 3
    assert counts["pumps"] == 20
    assert counts["tanks"] == 30
    assert counts["valves"] == 60
    assert counts["sensors"] * SCALES["full"][0] == 100_000


def test_generation_is_deterministic(tmp_path):
    a = export_files(generate_dataset(DEFAULT_SEED, "tiny"), tmp_path / "a")
    b = export_files(generate_dataset(DEFAULT_SEED, "tiny"), tmp_path / "b")
    assert a["sha256"] == b["sha256"]
    assert a["dataset_fingerprint"] == b["dataset_fingerprint"]


def test_different_seed_changes_data(tmp_path):
    a = export_files(generate_dataset(DEFAULT_SEED, "tiny"), tmp_path / "a")
    b = export_files(generate_dataset(DEFAULT_SEED + 1, "tiny"), tmp_path / "b")
    assert a["sha256"]["telemetry.csv"] != b["sha256"]["telemetry.csv"]


def test_deterministic_identifier_formats(db):
    assert db.scalars(select(Facility.id).order_by(Facility.id)).all() == ["FAC-001", "FAC-002", "FAC-003"]
    assert db.get(Pump, "PUMP-001") is not None and db.get(Pump, "PUMP-020") is not None
    assert db.get(Tank, "TANK-030") is not None
    assert db.get(Valve, "VALVE-060") is not None
    assert db.get(Sensor, "SNS-001") is not None
    for model, prefix in ((Pump, "PUMP"), (Tank, "TANK"), (Valve, "VALVE"), (Pipe, "PIPE"), (Sensor, "SNS")):
        assert all(is_valid_id(prefix, i) for i in db.scalars(select(model.id)))
    assert next_id(db, Pump.id, "PUMP") == "PUMP-021"
    assert next_simulation_id(db, 2026).startswith("SIM-2026-")


def test_all_equipment_references_are_valid(db):
    fac_ids = set(db.scalars(select(Facility.id)))
    nodes = {}
    for model in (Pump, Tank, Valve):
        for obj in db.scalars(select(model)):
            assert obj.facility_id in fac_ids
            nodes[obj.id] = obj
    for p in db.scalars(select(Pipe)):
        assert p.from_node_id in nodes and p.to_node_id in nodes
        assert nodes[p.from_node_id].facility_id == p.facility_id == nodes[p.to_node_id].facility_id
    eq = set(nodes) | set(db.scalars(select(Pipe.id)))
    for s in db.scalars(select(Sensor)):
        assert s.equipment_id in eq
    orphan = db.scalar(select(func.count(Telemetry.id)).where(~Telemetry.sensor_id.in_(select(Sensor.id))))
    assert orphan == 0


def test_derived_values_are_calculated_from_source(db):
    tel, _, tank = db.execute(
        select(Telemetry, Sensor, Tank).join(Sensor, Sensor.id == Telemetry.sensor_id)
        .join(Tank, Tank.id == Sensor.equipment_id)
        .where(Sensor.sensor_type == "LEVEL", Telemetry.value.is_not(None)).limit(1)).one()
    assert tel.derived_unit == "m3"
    assert np.isclose(tel.derived_value, tel.value / 100 * tank.capacity_m3, atol=1e-3)


def test_ground_truth_is_separate_file_and_references_valid_equipment(db, tmp_path):
    ds = generate_dataset(DEFAULT_SEED, "tiny")
    manifest = export_files(ds, tmp_path)
    gt = json.loads((tmp_path / "ground_truth.json").read_text())
    assert gt["labels"], "ground truth must contain labels"
    assert hashlib.sha256((tmp_path / "ground_truth.json").read_bytes()).hexdigest() == \
        manifest["sha256"]["ground_truth.json"]
    known = {s for m in ds.models.values() for s in list(m.pipes) + list(m.pumps) + list(m.sensors) + list(m.tanks)}
    for lab in gt["labels"]:
        assert lab["equipment_id"] in known
        assert lab["expected_severity"] in ("LOW", "MEDIUM", "HIGH", "CRITICAL")
        assert {"scenario_id", "issue_type", "start_timestamp", "end_timestamp", "expected_detection"} <= set(lab)
    # ground truth is never stored in the database
    assert not any("ground" in t for t in inspect(db.get_bind()).get_table_names())
