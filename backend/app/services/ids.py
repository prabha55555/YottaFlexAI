"""Deterministic, human-readable identifiers.

FAC-001, PUMP-001, TANK-001, VALVE-001, PIPE-001, SNS-001, MODE-001,
ANM-000001, ALM-000001, SIM-2026-000001.
New IDs are max(existing sequence) + 1 for the prefix, so IDs are never reused
within a database and generation order fully determines them.
"""
from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

ID_PATTERNS = {
    "FAC": re.compile(r"^FAC-\d{3,}$"),
    "PUMP": re.compile(r"^PUMP-\d{3,}$"),
    "TANK": re.compile(r"^TANK-\d{3,}$"),
    "VALVE": re.compile(r"^VALVE-\d{3,}$"),
    "PIPE": re.compile(r"^PIPE-\d{3,}$"),
    "SNS": re.compile(r"^SNS-\d{3,}$"),
    "MODE": re.compile(r"^MODE-\d{3,}$"),
    "ANM": re.compile(r"^ANM-\d{6,}$"),
    "ALM": re.compile(r"^ALM-\d{6,}$"),
    "SIM": re.compile(r"^SIM-\d{4}-\d{6,}$"),
}


def format_id(prefix: str, n: int, width: int = 3) -> str:
    return f"{prefix}-{n:0{width}d}"


def _max_seq(db: Session, column, prefix: str) -> int:
    rows = db.scalars(select(column).where(column.like(f"{prefix}-%"))).all()
    best = 0
    for r in rows:
        tail = r[len(prefix) + 1:]
        if tail.isdigit():
            best = max(best, int(tail))
    return best


def next_id(db: Session, column, prefix: str, width: int = 3) -> str:
    return format_id(prefix, _max_seq(db, column, prefix) + 1, width)


class SequenceAllocator:
    """Allocate many sequential IDs in one transaction without re-querying."""

    def __init__(self, db: Session, column, prefix: str, width: int):
        self.prefix, self.width = prefix, width
        self.n = _max_seq(db, column, prefix)

    def __call__(self) -> str:
        self.n += 1
        return format_id(self.prefix, self.n, self.width)


def next_simulation_id(db: Session, year: int) -> str:
    from app.models import SimulationRun

    prefix = f"SIM-{year}"
    return format_id(prefix, _max_seq(db, SimulationRun.id, prefix) + 1, 6)


def is_valid_id(prefix: str, value: str) -> bool:
    pat = ID_PATTERNS.get(prefix)
    return bool(pat and pat.match(value or ""))
