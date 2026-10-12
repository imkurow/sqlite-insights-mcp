from datetime import date
from pathlib import Path

import pytest

from db import DB_PATH_ENV
from seed import build_database

FIXED_TODAY = date(2026, 10, 12)


@pytest.fixture
def sample_db(tmp_path, monkeypatch) -> Path:
    path = build_database(tmp_path / "sample.db", today=FIXED_TODAY)
    monkeypatch.setenv(DB_PATH_ENV, str(path))
    return path


@pytest.fixture
def anyio_backend():
    return "asyncio"
