"""The SQLite engine: pragmas on every connection, how transactions begin, and the UTC column type."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import Integer, event, text
from sqlalchemy.exc import StatementError
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from formlens.database import BUSY_TIMEOUT_MS, Database, UtcDateTime


class StampBase(DeclarativeBase):
    """Its own metadata: the table must not appear in the one the migrations are compared with."""


class Stamp(StampBase):
    __tablename__ = "test_stamps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    at: Mapped[datetime | None] = mapped_column(UtcDateTime(), nullable=True)


@pytest.fixture
def database(tmp_path: Path) -> Iterator[Database]:
    db = Database(f"sqlite:///{tmp_path / 'test.db'}")
    StampBase.metadata.create_all(db.engine)
    yield db
    db.dispose()


def statements(database: Database) -> list[str]:
    """Record every statement the engine sends from now on."""
    seen: list[str] = []

    @event.listens_for(database.engine, "before_cursor_execute")
    def record(_conn: object, _cursor: object, statement: str, *_rest: object) -> None:
        seen.append(statement)

    return seen


def test_every_connection_gets_wal_a_busy_timeout_and_foreign_keys(database: Database) -> None:
    with database.read() as session:
        journal = session.execute(text("PRAGMA journal_mode")).scalar_one()
        busy = session.execute(text("PRAGMA busy_timeout")).scalar_one()
        foreign_keys = session.execute(text("PRAGMA foreign_keys")).scalar_one()

    assert (journal, busy, foreign_keys) == ("wal", BUSY_TIMEOUT_MS, 1)


def test_a_write_transaction_takes_the_write_lock_and_a_read_does_not(database: Database) -> None:
    seen = statements(database)

    with database.read() as session:
        session.execute(text("SELECT 1"))
    with database.write() as session:
        session.execute(text("SELECT 1"))

    begins = [s for s in seen if s.startswith("BEGIN")]
    assert begins == ["BEGIN", "BEGIN IMMEDIATE"]


def test_a_write_is_committed_when_the_block_ends(database: Database) -> None:
    with database.write() as session:
        session.add(Stamp(id=1))

    with database.read() as session:
        assert session.get(Stamp, 1) is not None


def write_then_fail(database: Database, stamp_id: int) -> None:
    with database.write() as session:
        session.add(Stamp(id=stamp_id))
        session.flush()
        raise RuntimeError("boom")


def test_a_write_is_rolled_back_when_the_block_raises(database: Database) -> None:
    with pytest.raises(RuntimeError, match="boom"):
        write_then_fail(database, 2)

    with database.read() as session:
        assert session.get(Stamp, 2) is None


def test_the_same_row_can_be_written_after_a_failed_write(database: Database) -> None:
    with pytest.raises(RuntimeError, match="boom"):
        write_then_fail(database, 3)

    with database.write() as session:
        session.add(Stamp(id=3))

    with database.read() as session:
        assert session.get(Stamp, 3) is not None


def test_building_the_database_creates_no_file(tmp_path: Path) -> None:
    path = tmp_path / "lazy.db"

    Database(f"sqlite:///{path}").dispose()

    assert not path.exists()


def test_a_timestamp_comes_back_as_the_same_instant_in_utc(database: Database) -> None:
    local = datetime(2026, 3, 1, 12, 0, tzinfo=timezone(timedelta(hours=2)))
    with database.write() as session:
        session.add(Stamp(id=1, at=local))

    with database.read() as session:
        stored = session.get(Stamp, 1)

    assert stored is not None
    assert stored.at == local
    assert stored.at is not None
    assert stored.at.tzinfo is UTC
    assert stored.at.hour == 10


def add_naive_timestamp(database: Database) -> None:
    with database.write() as session:
        session.add(Stamp(id=1, at=datetime(2026, 3, 1, 12, 0)))  # noqa: DTZ001  # the point of the test


def test_a_naive_timestamp_is_refused(database: Database) -> None:
    with pytest.raises(StatementError, match="naive datetime"):
        add_naive_timestamp(database)


def test_an_empty_timestamp_stays_empty(database: Database) -> None:
    with database.write() as session:
        session.add(Stamp(id=1, at=None))

    with database.read() as session:
        stored = session.get(Stamp, 1)

    assert stored is not None
    assert stored.at is None
