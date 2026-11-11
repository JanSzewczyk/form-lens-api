"""Fixtures of the parsing tests: the app is built around one `FakeParser` the test can read."""

from collections.abc import Iterator

import pytest
from fastapi import FastAPI

from formlens.config import Settings
from formlens.main import create_app
from tests.fakes import FakeParser


@pytest.fixture
def parser() -> FakeParser:
    """The parser the app loads at startup; read `calls` and `max_running` from it."""
    return FakeParser()


@pytest.fixture
def app(settings: Settings, parser: FakeParser) -> Iterator[FastAPI]:
    """The app of the parsing tests; it replaces the shared fixture so a test sees its parser."""
    application = create_app(settings, parser_factory=lambda _: parser)
    yield application
    application.dependency_overrides.clear()
    application.state.database.dispose()
