"""Shared fixtures: settings that ignore the environment file, an app and a client."""

import os
import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from formlens.config import ModelSettings, Settings
from formlens.main import create_app
from formlens.migrations import upgrade_to_head
from tests.fakes import FakeParser
from tests.probes import add_probe_routes

#: The settings a `slow` test takes from the outside: the model files and the language model it talks to.
LLM_SETTINGS = ("llm_base_url", "llm_model")


def make_settings(**overrides: Any) -> Settings:
    """Build Settings for a test: no `.env` file, environment `test`, overrides on top."""
    values: dict[str, Any] = {"environment": "test", **overrides}
    return Settings(_env_file=None, **values)


def slow_settings() -> Settings:
    """Settings for a test with the real models: only the model settings come from outside.

    `MODELS_PATH` and `VLM_BACKEND` are read like the service and `make download-models` read them (the
    environment, then `.env`), through `ModelSettings`, which ignores the rest of `.env`. `LLM_BASE_URL`
    and `LLM_MODEL` are taken from the environment when it sets them. Everything else is the test default.
    """
    models = ModelSettings()
    llm = {name: os.environ[name.upper()] for name in LLM_SETTINGS if name.upper() in os.environ}
    return make_settings(models_path=models.models_path, vlm_backend=models.vlm_backend, **llm)


@pytest.fixture(autouse=True)
def _isolate_from_exported_settings(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove every setting from the environment, so an exported `DOCS_ENABLED` cannot change a test.

    `Settings(_env_file=None)` skips the file but not the shell. The `slow` tests keep `MODELS_PATH` and
    `VLM_BACKEND` (`make test-models MODELS_PATH=/data/models`) and the two LLM settings
    (`make test-models LLM_MODEL=...`), and lose the other settings like any test.
    """
    names = {name.upper() for name in Settings.model_fields}
    if request.node.get_closest_marker("slow") is not None:
        names -= {name.upper() for name in (*ModelSettings.model_fields, *LLM_SETTINGS)}
    for key in list(os.environ):  # settings names are case-insensitive
        if key.upper() in names:
            monkeypatch.delenv(key)


@pytest.fixture(scope="session")
def migrated_database(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A database file with every migration applied; each test gets its own copy (see `settings`)."""
    path = tmp_path_factory.mktemp("migrated") / "formlens.db"
    upgrade_to_head(f"sqlite:///{path}")
    return path


@pytest.fixture
def settings(tmp_path: Path, migrated_database: Path) -> Settings:
    """Default test settings, with a private copy of the migrated database as `DB_URL`.

    A real file, not an in-memory database: the tests of the race guards need connections that really compete.
    A test never touches `./formlens.db`.
    """
    database = tmp_path / "formlens.db"
    shutil.copyfile(migrated_database, database)
    return make_settings(db_url=f"sqlite:///{database}")


@pytest.fixture
def app(settings: Settings) -> Iterator[FastAPI]:
    """Application built from the test settings; dependency overrides are cleared afterwards."""
    application = create_app(settings, parser_factory=lambda _: FakeParser())
    yield application
    application.dependency_overrides.clear()
    application.state.database.dispose()


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
