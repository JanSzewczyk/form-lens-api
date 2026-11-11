"""Database migrations (Alembic), run by `python -m formlens migrate`; the service never creates tables itself."""

from typing import Final, cast

import structlog
from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine

from formlens.database import Database

log = structlog.get_logger(__name__)

# `package:folder` form: the scripts are found inside the installed package, wherever it lives, so no
# `alembic.ini` and no working-directory dependence.
SCRIPT_LOCATION: Final = "formlens:migrations"
HINT: Final = "run `make migrate` (python -m formlens migrate), then start the service again"


class DatabaseNotAtHead(Exception):
    """The database is not at the newest revision the code expects."""

    def __init__(self, current: str | None, head: str) -> None:
        """Name the revision found and the one expected."""
        super().__init__(f"The database is at revision {current or 'none (empty)'}, the code needs {head}.")
        self.current = current
        self.head = head


def _config(url: str | None = None) -> Config:
    """Build the Alembic configuration in code; `env.py` reads the URL from `attributes`."""
    config = Config()
    config.set_main_option("script_location", SCRIPT_LOCATION)
    config.attributes["url"] = url
    return config


def head_revision() -> str:
    """Return the newest revision the code ships."""
    return cast("str", ScriptDirectory.from_config(_config()).get_current_head())


def current_revision(engine: Engine) -> str | None:
    """Return the revision the database is at, or None for a database that was never migrated."""
    with engine.connect() as connection:
        return MigrationContext.configure(connection).get_current_revision()


def upgrade_to_head(url: str) -> None:
    """Create or update the schema of the database at `url`."""
    command.upgrade(_config(url), "head")


def downgrade_to_base(url: str) -> None:
    """Remove every table the migrations created (used by the migration test)."""
    command.downgrade(_config(url), "base")


def assert_at_head(database: Database) -> None:
    """Raise `DatabaseNotAtHead` unless the database is at the newest revision."""
    current = current_revision(database.engine)
    head = head_revision()
    if current != head:
        raise DatabaseNotAtHead(current, head)
