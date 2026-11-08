"""Shared fixtures: settings that ignore the environment file, an app and a client."""

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from fastapi_szumplate.config import Settings
from fastapi_szumplate.main import create_app
from tests.probes import add_probe_routes


def make_settings(**overrides: Any) -> Settings:
    """Build Settings for a test: no `.env` file, environment `test`, overrides on top."""
    values: dict[str, Any] = {"environment": "test", **overrides}
    return Settings(_env_file=None, **values)


@pytest.fixture
def settings() -> Settings:
    """Default test settings."""
    return make_settings()


@pytest.fixture
def app(settings: Settings) -> Iterator[FastAPI]:
    """Application built from the test settings; dependency overrides are cleared afterwards."""
    application = create_app(settings)
    yield application
    application.dependency_overrides.clear()


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    """Test client bound to the app."""
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def probe_app(app: FastAPI) -> FastAPI:
    """The app with the test-only probe routes of `tests/probes.py` mounted."""
    return add_probe_routes(app)


@pytest.fixture
def probe(probe_app: FastAPI) -> Iterator[TestClient]:
    """A client for `probe_app` that gets a 500 response instead of the re-raised exception."""
    with TestClient(probe_app, raise_server_exceptions=False) as test_client:
        yield test_client
