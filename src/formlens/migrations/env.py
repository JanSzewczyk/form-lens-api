"""Alembic environment: the database is the one `upgrade_to_head` names, the models come from the table modules.

It never calls `logging.config.fileConfig`: that would replace the handlers `configure_logging` installed.
"""

from alembic import context

import formlens.templates.tables  # noqa: F401  # registers the table on Base.metadata
from formlens.database import Base, Database

config = context.config
target_metadata = Base.metadata


def run_migrations() -> None:
    """Run the migrations in one transaction on a connection of the pragma-configured engine."""
    database = Database(config.attributes["url"])
    try:
        with database.engine.connect() as connection:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                render_as_batch=True,
                compare_type=True,
            )
            with context.begin_transaction():
                context.run_migrations()
    finally:
        database.dispose()


run_migrations()
