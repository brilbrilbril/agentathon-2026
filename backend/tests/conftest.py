import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from app.database import SessionLocal


@pytest.fixture(scope="session")
def db_session():
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture(scope="session")
def case_text() -> str:
    fixture_path = Path(__file__).parent / "fixtures" / "case_12246557.txt"
    return fixture_path.read_text(encoding="utf-8")
