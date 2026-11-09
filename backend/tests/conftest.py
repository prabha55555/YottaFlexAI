"""Test fixtures: an isolated temporary database + data directory, loaded with the
deterministic 'tiny' dataset. Environment variables must be set before any
``app`` import so the engine binds to the temporary database."""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="yottaflex_test_"))
os.environ["YOTTAFLEX_DATA_DIR"] = str(_TMP)
os.environ["YOTTAFLEX_DB_URL"] = f"sqlite:///{(_TMP / 'test.db').as_posix()}"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.config import DEFAULT_SEED  # noqa: E402
from app.database import SessionLocal, engine  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def loaded_db():
    from scripts.generate_data import main

    assert main(["--seed", str(DEFAULT_SEED), "--scale", "tiny"]) == 0
    yield
    engine.dispose()
    shutil.rmtree(_TMP, ignore_errors=True)


@pytest.fixture()
def db():
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture(scope="session")
def client(loaded_db):
    from app.main import app

    with TestClient(app) as c:
        yield c
