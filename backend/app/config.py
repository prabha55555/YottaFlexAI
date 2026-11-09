"""Central configuration. Values can be overridden with environment variables."""
from __future__ import annotations

import os
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("YOTTAFLEX_DATA_DIR", BACKEND_DIR / "data"))
GENERATED_DIR = DATA_DIR / "generated"
NEGATIVE_CASES_DIR = BACKEND_DIR / "negative_cases"

DEFAULT_DB_URL = f"sqlite:///{(DATA_DIR / 'yottaflex.db').as_posix()}"
DATABASE_URL = os.getenv("YOTTAFLEX_DB_URL", DEFAULT_DB_URL)

DEFAULT_SEED = 20261022

# Physical constants (water at ~20 degC)
RHO_G_BAR_PER_M = 0.0981  # 1 m of water column ~= 0.0981 bar

# Mass-balance tolerances (percent of total inflow)
MASS_BALANCE_TOLERANCE_PCT = float(os.getenv("YOTTAFLEX_MB_TOLERANCE_PCT", "2.0"))
MASS_BALANCE_WARNING_FACTOR = 2.0  # WARNING band: tol < err <= tol * factor

CORS_ORIGINS = os.getenv(
    "YOTTAFLEX_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
).split(",")
