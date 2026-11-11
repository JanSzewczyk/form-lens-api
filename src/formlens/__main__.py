"""Command line: `python -m formlens` serves the API, `python -m formlens migrate` updates the database."""

import argparse
import sys
from collections.abc import Sequence

import structlog
import uvicorn

from formlens.config import Settings
from formlens.logging_config import configure_logging
from formlens.migrations import head_revision, upgrade_to_head

log = structlog.get_logger(__name__)


def main() -> None:
    """Configure logging, then run uvicorn on the app factory (which configures it again)."""
    settings = Settings()
    configure_logging(settings)
    uvicorn.run(
        "formlens.main:create_app",
        factory=True,
        host=settings.host,
        port=settings.port,
        reload=settings.reload,
        timeout_graceful_shutdown=settings.graceful_shutdown_seconds,
        server_header=False,  # do not announce the server software
        log_config=None,  # our handler is already installed; uvicorn must not replace it
        access_log=False,  # RequestContextMiddleware writes the access line
    )


def migrate() -> None:
    """Bring the database of `DB_URL` to the newest revision; run it before the first start and after an update."""
    settings = Settings()
    configure_logging(settings)
    upgrade_to_head(settings.db_url)
    log.info("database_migrated", revision=head_revision())


def run(argv: Sequence[str]) -> None:
    """Run the command named in `argv`; with none, serve."""
    parser = argparse.ArgumentParser(prog="python -m formlens", description=__doc__)
    commands = parser.add_subparsers(dest="command", metavar="command")
    commands.add_parser("serve", help="start the API (the default)")
    commands.add_parser("migrate", help="create or update the database tables")
    args = parser.parse_args(argv)
    if args.command == "migrate":
        migrate()
    else:
        main()


def cli() -> None:
    """Entry point of the `formlens` script and of `python -m formlens`."""
    run(sys.argv[1:])


if __name__ == "__main__":
    cli()
