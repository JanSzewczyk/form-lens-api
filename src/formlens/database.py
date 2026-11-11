"""The SQLite database: engine, session helpers, the declarative base and the UTC datetime column type."""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any, Final

from sqlalchemy import DateTime, Engine, MetaData, create_engine, event
from sqlalchemy.engine import Connection, Dialect
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import ConnectionPoolEntry
from sqlalchemy.types import TypeDecorator, TypeEngine

# Seconds a writer waits for the write lock before SQLite answers "database is locked".
BUSY_TIMEOUT_MS: Final = 5000
# Named constraints: Alembic's batch mode on SQLite cannot drop or alter an unnamed one.
NAMING_CONVENTION: Final = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}
_WRITE_OPTION: Final = "formlens_write"


class Base(DeclarativeBase):
    """Base of every table; its metadata is what Alembic compares the database with."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class UtcDateTime(TypeDecorator[datetime]):
    """A timestamp that is always timezone-aware UTC in Python and naive UTC in SQLite.

    SQLite has no timezone type and drops the offset, so a naive value would be read back as local
    time by the next reader. This type refuses a naive value on the way in and restores UTC on the way out.
    """

    impl: TypeEngine[Any] | type[TypeEngine[Any]] = DateTime(timezone=True)
    cache_ok: bool | None = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:  # noqa: ARG002
        """Store UTC; refuse a naive datetime."""
        if value is None:
            return None
        if value.tzinfo is None:
            msg = "a naive datetime has no zone; pass an aware one"
            raise ValueError(msg)
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:  # noqa: ARG002
        """Read the stored value back as UTC."""
        return None if value is None else value.replace(tzinfo=UTC)


def _on_connect(dbapi_connection: sqlite3.Connection, _record: ConnectionPoolEntry) -> None:
    """Set the pragmas of every new connection and hand the transactions over to SQLAlchemy.

    `isolation_level = None` stops the driver from opening transactions on its own, so the `begin`
    hook below decides how each one starts. WAL lets readers go on while one writer works.
    """
    dbapi_connection.isolation_level = None
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA synchronous=NORMAL")
    finally:
        cursor.close()


def _on_begin(connection: Connection) -> None:
    """Start a write transaction with the write lock, so two writers queue instead of failing late.

    A plain `BEGIN` takes the lock at the first write; a transaction that read first and then wants to
    write fails with SQLITE_BUSY when another writer got in between. `BEGIN IMMEDIATE` fails or waits at
    the start, where nothing has been read yet.
    """
    if connection.get_execution_options().get(_WRITE_OPTION, False):
        connection.exec_driver_sql("BEGIN IMMEDIATE")
    else:
        connection.exec_driver_sql("BEGIN")


class Database:
    """One SQLite engine and the two kinds of session built on it.

    Building it opens no connection and creates no file; the first query does. Each repository method
    is one short transaction on a fresh session, from `read()` or `write()`.
    """

    def __init__(self, url: str) -> None:
        """Create the engine for `url`; the pragmas run on every connection the pool opens."""
        self.engine: Engine = create_engine(url, connect_args={"check_same_thread": False})
        event.listen(self.engine, "connect", _on_connect)
        event.listen(self.engine, "begin", _on_begin)
        self._write_engine = self.engine.execution_options(**{_WRITE_OPTION: True})
        self._read = sessionmaker(self.engine, expire_on_commit=False)
        self._write = sessionmaker(self._write_engine, expire_on_commit=False)

    @contextmanager
    def read(self) -> Iterator[Session]:
        """Yield a session for reading; it is closed, and its transaction ended, afterwards."""
        with self._read() as session:
            yield session

    @contextmanager
    def write(self) -> Iterator[Session]:
        """Yield a session whose transaction holds the write lock; commit on success, roll back on error."""
        with self._write() as session:
            try:
                yield session
                session.commit()
            except BaseException:
                session.rollback()
                raise

    def dispose(self) -> None:
        """Close every pooled connection."""
        self.engine.dispose()
