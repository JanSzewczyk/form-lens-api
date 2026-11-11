"""The app that `make schemathesis` fuzzes: the real application with a fake parser, so no model is loaded.

Schemathesis sends thousands of requests. A real model would turn that into hours and would test the
model, not the contract. The production code has no switch for a fake parser: the factory is here, in
the tests, and the script starts it with `uvicorn --factory`:

    uvicorn --factory tests.schemathesis_app:create_schemathesis_app

Everything else (settings from the environment, middleware, error handlers, body cap) is the real thing.
"""

from fastapi import FastAPI

from formlens.config import Settings
from formlens.main import create_app
from tests.fakes import FakeParser


def create_schemathesis_app() -> FastAPI:
    """Build the app from the environment (`ENVIRONMENT`, `LOG_*`, `MAX_UPLOAD_MB`) with a `FakeParser`."""
    return create_app(Settings(), parser_factory=lambda _: FakeParser())
