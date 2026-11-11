"""The migrations: they run on a real file, undo themselves, and describe exactly the models."""

import logging
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import inspect

import formlens.extractions.adapters.tables  # registers its tables on Base.metadata for the comparison
import formlens.templates.tables  # noqa: F401
from formlens.database import Base, Database
from formlens.logging_config import configure_logging
from formlens.migrations import (
    DatabaseNotAtHead,
    assert_at_head,
    current_revision,
    downgrade_to_base,
    head_revision,
    upgrade_to_head,
)
from tests.conftest import make_settings


@pytest.fixture
def url(tmp_path: Path) -> str:
    return f"sqlite:///{tmp_path / 'migrated.db'}"


@pytest.fixture
def database(url: str) -> Iterator[Database]:
    db = Database(url)
    yield db
    db.dispose()


def table_names(database: Database) -> set[str]:
    return set(inspect(database.engine).get_table_names())


def test_a_new_database_is_upgraded_to_the_head_revision(url: str, database: Database) -> None:
    upgrade_to_head(url)

    assert current_revision(database.engine) == head_revision()
    assert {"alembic_version", "templates", "extractions", "extraction_inputs"} <= table_names(database)


def test_upgrading_twice_changes_nothing(url: str, database: Database) -> None:
    upgrade_to_head(url)
    upgrade_to_head(url)

    assert current_revision(database.engine) == head_revision()


def test_downgrading_to_base_removes_every_table_of_the_models(url: str, database: Database) -> None:
    upgrade_to_head(url)

    downgrade_to_base(url)

    assert table_names(database) == {"alembic_version"}
    assert current_revision(database.engine) is None


def test_upgrade_after_a_downgrade_restores_the_schema(url: str, database: Database) -> None:
    upgrade_to_head(url)
    created = table_names(database)
    downgrade_to_base(url)

    upgrade_to_head(url)

    assert table_names(database) == created


def test_the_migrated_schema_matches_the_models_exactly(url: str, database: Database) -> None:
    """A model changed without a migration (or the reverse) shows up as a difference here."""
    upgrade_to_head(url)

    with database.engine.connect() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": True, "render_as_batch": True})
        differences = compare_metadata(context, Base.metadata)

    assert differences == []


def test_the_service_check_refuses_an_empty_database(url: str, database: Database) -> None:
    with pytest.raises(DatabaseNotAtHead, match="none"):
        assert_at_head(database)


def test_the_service_check_accepts_a_migrated_database(url: str, database: Database) -> None:
    upgrade_to_head(url)

    assert_at_head(database)


def test_the_service_check_refuses_a_database_behind_the_code(url: str, database: Database) -> None:
    upgrade_to_head(url)
    downgrade_to_base(url)

    with pytest.raises(DatabaseNotAtHead) as raised:
        assert_at_head(database)

    assert raised.value.current is None
    assert raised.value.head == head_revision()


def test_a_migration_leaves_the_logging_of_the_application_alone(url: str) -> None:
    """`fileConfig` would replace every handler; the migration must keep the one `configure_logging` set."""
    configure_logging(make_settings(log_format="json"))
    before = list(logging.getLogger().handlers)

    upgrade_to_head(url)

    assert logging.getLogger().handlers == before
