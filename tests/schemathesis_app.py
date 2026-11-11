"""The app that `make schemathesis` fuzzes: the real application with a fake parser and a fake extractor.

Schemathesis sends thousands of requests. A real model would turn that into hours and would test the
model, not the contract. The production code has no switch for a fake parser or extractor: the factory is
here, in the tests, and the script starts it with `uvicorn --factory`. The worker is off, so queued
extractions stay `pending` and the run is the same every time. The database is the one `DB_URL` names; the
script migrates a temporary file first:

    uvicorn --factory tests.schemathesis_app:create_schemathesis_app

Everything else (settings from the environment, middleware, error handlers, body cap) is the real thing.
"""

from fastapi import FastAPI

from formlens.config import Settings
from formlens.main import create_app
from tests.extractions.fakes import FakeExtractor
from tests.fakes import FakeParser


def create_schemathesis_app() -> FastAPI:
    """Build the app from the environment (`ENVIRONMENT`, `DB_URL`, `LOG_*`, ...) with a fake parser and extractor."""
    return create_app(
        Settings(),
        parser_factory=lambda _: FakeParser(),
        extractor_factory=lambda _: FakeExtractor(),
        start_worker=False,
    )
