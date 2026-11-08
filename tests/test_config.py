from pathlib import Path
from typing import Annotated

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from fastapi_szumplate.config import Settings, get_settings
from fastapi_szumplate.main import create_app
from tests.conftest import make_settings

ENV_EXAMPLE = Path(__file__).resolve().parent.parent / ".env.example"


def test_defaults_are_safe_for_a_public_api() -> None:
    settings = Settings(_env_file=None)

    assert settings.docs_enabled is False
    assert settings.cors_origins == []
    assert settings.log_level == "INFO"


def test_a_copied_env_example_keeps_the_docs_off_in_production() -> None:
    """`cp .env.example .env` is the documented first step; it must not publish /docs."""
    settings = Settings(_env_file=ENV_EXAMPLE, environment="production")

    assert settings.docs_enabled is False
    assert TestClient(create_app(settings)).get("/docs").status_code == 404


def test_env_example_states_the_defaults() -> None:
    """The file says "the values below are the defaults unless noted"."""
    assert Settings(_env_file=ENV_EXAMPLE) == Settings(_env_file=None)


def test_environment_variables_override_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PORT", "9100")
    monkeypatch.setenv("DOCS_ENABLED", "true")
    monkeypatch.setenv("CORS_ORIGINS", '["https://app.example.com"]')

    settings = Settings(_env_file=None)

    assert settings.port == 9100
    assert settings.docs_enabled is True
    assert settings.cors_origins == ["https://app.example.com"]


@pytest.mark.parametrize(
    ("field", "value"),
    [("log_level", "LOUD"), ("environment", "staging"), ("port", 0), ("default_page_size", 101)],
    ids=["log-level", "environment", "port", "page-size"],
)
def test_invalid_values_are_rejected(field: str, value: object) -> None:
    with pytest.raises(ValidationError, match=field):
        make_settings(**{field: value})


@pytest.mark.parametrize(
    ("environment", "log_format", "expected"),
    [
        ("local", "auto", "console"),
        ("production", "auto", "json"),
        ("local", "json", "json"),
        ("production", "console", "console"),
    ],
    ids=["auto-local", "auto-production", "explicit-json", "explicit-console"],
)
def test_log_format_resolves_from_environment(environment: str, log_format: str, expected: str) -> None:
    settings = make_settings(environment=environment, log_format=log_format)

    assert settings.resolved_log_format == expected


def test_get_settings_returns_the_settings_of_the_running_app(app: FastAPI) -> None:
    @app.get("/_settings", operation_id="get_settings_probe")
    def probe(settings: Annotated[Settings, Depends(get_settings)]) -> dict[str, str]:
        return {"name": settings.app_name}

    app.state.settings = make_settings(app_name="probe-app")

    assert TestClient(app).get("/_settings").json() == {"name": "probe-app"}
