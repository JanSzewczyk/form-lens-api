"""The repository under test: the fake and the SQLite adapter, each on its own."""

import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest

from formlens.database import Database
from formlens.extractions.adapters.sqlite_repository import SqliteExtractionRepository
from formlens.extractions.domain.ports import ExtractionRepository
from tests.extractions.fakes import FakeExtractionRepository


@pytest.fixture
def database(tmp_path: Path, migrated_database: Path) -> Iterator[Database]:
    """A private copy of the migrated database file; a real file, so connections really compete."""
    path = tmp_path / "extractions.db"
    shutil.copyfile(migrated_database, path)
    db = Database(f"sqlite:///{path}")
    yield db
    db.dispose()


@pytest.fixture(params=["fake", "sqlite"])
def repository(request: pytest.FixtureRequest) -> Iterator[ExtractionRepository]:
    """Every contract test runs once per implementation."""
    if request.param == "fake":
        yield FakeExtractionRepository()
    else:
        database: Database = request.getfixturevalue("database")
        yield SqliteExtractionRepository(database)
