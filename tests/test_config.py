import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Annotated

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from formlens.config import LlmSettings, ModelSettings, Settings, get_settings
from formlens.main import create_app
from tests.conftest import make_settings, slow_settings

ENV_EXAMPLE = Path(__file__).resolve().parent.parent / ".env.example"


def test_defaults_are_safe_for_a_public_api() -> None:
    settings = Settings(_env_file=None)

    assert settings.docs_enabled is False
    assert settings.cors_origins == []
    assert settings.log_level == "INFO"


def test_model_settings_default_to_the_local_apple_silicon_setup() -> None:
    settings = Settings(_env_file=None)

    assert settings.models_path == Path("models")
    assert settings.vlm_backend == "mlx"
    assert settings.max_upload_mb == 25
    assert settings.max_concurrency == 1
    assert settings.parse_timeout_seconds == 300


def test_job_and_model_settings_default_to_a_local_sqlite_file_and_a_local_ollama() -> None:
    settings = Settings(_env_file=None)

    assert settings.db_url == "sqlite:///./formlens.db"
    assert settings.llm_base_url == "http://localhost:11434/v1"
    assert settings.llm_model == "qwen3:8b"
    assert settings.llm_timeout_seconds == 120
    assert settings.llm_max_input_chars == 20000
    assert settings.result_ttl_hours == 24
    assert settings.job_timeout_seconds == 600
    assert settings.job_max_attempts == 2
    assert settings.job_poll_interval_seconds == 2.0
    assert settings.queue_max_pending == 100


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
    monkeypatch.setenv("MODELS_PATH", "/srv/models")
    monkeypatch.setenv("VLM_BACKEND", "transformers")
    monkeypatch.setenv("MAX_UPLOAD_MB", "5")
    monkeypatch.setenv("MAX_CONCURRENCY", "2")

    settings = Settings(_env_file=None)

    assert settings.port == 9100
    assert settings.docs_enabled is True
    assert settings.cors_origins == ["https://app.example.com"]
    assert settings.models_path == Path("/srv/models")
    assert settings.vlm_backend == "transformers"
    assert settings.max_upload_mb == 5
    assert settings.max_concurrency == 2


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("log_level", "LOUD"),
        ("environment", "staging"),
        ("port", 0),
        ("default_page_size", 101),
        ("vlm_backend", "cuda"),
        ("max_concurrency", 0),
        ("max_upload_mb", 0),
    ],
    ids=["log-level", "environment", "port", "page-size", "vlm-backend", "max-concurrency", "max-upload-mb"],
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


# --- Stage 0 contract tests: model settings, environment handling, `.env.example` -----------------

ROOT = Path(__file__).resolve().parent.parent

#: A value that differs from the default, for every setting. A new setting must be added here (the
#: test below fails until it is), so the isolation test always covers every field.
NON_DEFAULT_ENVIRONMENT = {
    "APP_NAME": "from-the-shell",
    "ENVIRONMENT": "production",
    "LOG_LEVEL": "DEBUG",
    "LOG_FORMAT": "console",
    "DOCS_ENABLED": "true",
    "CORS_ORIGINS": '["https://shell.example.com"]',
    "HOST": "0.0.0.0",  # noqa: S104  # a value to be ignored, never bound
    "PORT": "9999",
    "RELOAD": "true",
    "GRACEFUL_SHUTDOWN_SECONDS": "3",
    "DEFAULT_PAGE_SIZE": "5",
    "MODELS_PATH": "/from/the/shell",
    "VLM_BACKEND": "transformers",
    "MAX_UPLOAD_MB": "5",
    "MAX_JSON_BODY_KB": "64",
    "MAX_CONCURRENCY": "3",
    "PARSE_TIMEOUT_SECONDS": "7",
    "DB_URL": "sqlite:////from/the/shell.db",
    "LLM_BASE_URL": "http://ollama:11435/v1",
    "LLM_MODEL": "from-the-shell:1b",
    "LLM_TIMEOUT_SECONDS": "11",
    "LLM_MAX_INPUT_CHARS": "99",
    "RESULT_TTL_HOURS": "5",
    "JOB_TIMEOUT_SECONDS": "50",
    "JOB_MAX_ATTEMPTS": "4",
    "JOB_POLL_INTERVAL_SECONDS": "0.5",
    "QUEUE_MAX_PENDING": "3",
}


def test_the_isolation_test_below_covers_every_setting() -> None:
    assert set(NON_DEFAULT_ENVIRONMENT) == {name.upper() for name in Settings.model_fields}


def test_a_settings_object_built_without_arguments_holds_every_declared_default() -> None:
    """The shell's exported settings never reach `Settings(_env_file=None)`: the autouse fixture removes them."""
    declared = {name: field.get_default(call_default_factory=True) for name, field in Settings.model_fields.items()}

    assert Settings(_env_file=None).model_dump() == declared


def test_the_settings_tests_pass_when_the_shell_exports_every_setting() -> None:
    """A developer who exports `DOCS_ENABLED=true` or `VLM_BACKEND=transformers` sees no failing test.

    Every test builds Settings with `_env_file=None`, which skips the file but not the shell. The autouse
    fixture in `tests/conftest.py` deletes the settings from the environment; the `slow` tests keep
    `MODELS_PATH` and `VLM_BACKEND`: `make test-models MODELS_PATH=/data/models` (README) needs them.
    The child run holds the tests that read the defaults, so it fails when the fixture stops deleting a variable.
    """
    environment = {**os.environ, **NON_DEFAULT_ENVIRONMENT}
    here = "tests/test_config.py"

    result = subprocess.run(  # noqa: S603  # this interpreter, fixed arguments
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            f"{here}::test_defaults_are_safe_for_a_public_api",
            f"{here}::test_model_settings_default_to_the_local_apple_silicon_setup",
            f"{here}::test_a_settings_object_built_without_arguments_holds_every_declared_default",
        ],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )

    assert result.returncode == 0, result.stdout[-2000:]
    assert "3 passed" in result.stdout


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("MAX_UPLOAD_MB", "0"),
        ("MAX_UPLOAD_MB", "-1"),
        ("MAX_UPLOAD_MB", "abc"),
        ("MAX_UPLOAD_MB", "1.5"),
        ("MAX_UPLOAD_MB", ""),
        ("MODELS_PATH", ""),
        ("PARSE_TIMEOUT_SECONDS", "0"),
        ("PARSE_TIMEOUT_SECONDS", "-5"),
        ("PARSE_TIMEOUT_SECONDS", "soon"),
        ("MAX_CONCURRENCY", "0"),
        ("MAX_CONCURRENCY", "-3"),
        ("MAX_CONCURRENCY", "two"),
        ("VLM_BACKEND", "cuda"),
        ("VLM_BACKEND", "MLX"),
        ("VLM_BACKEND", " mlx"),
    ],
    ids=[
        "upload-zero",
        "upload-negative",
        "upload-text",
        "upload-fraction",
        "upload-empty",
        "models-path-empty",
        "timeout-zero",
        "timeout-negative",
        "timeout-text",
        "concurrency-zero",
        "concurrency-negative",
        "concurrency-text",
        "backend-unknown",
        "backend-wrong-case",
        "backend-padded",
    ],
)
def test_an_invalid_model_setting_in_the_environment_stops_the_app_from_being_built(
    monkeypatch: pytest.MonkeyPatch, name: str, value: str
) -> None:
    monkeypatch.setenv(name, value)

    with pytest.raises(ValidationError, match=name.lower()):
        create_app()


@pytest.mark.parametrize("name", ["MAX_UPLOAD_MB", "MAX_CONCURRENCY", "PARSE_TIMEOUT_SECONDS"])
def test_one_is_the_smallest_accepted_count(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    monkeypatch.setenv(name, "1")

    assert getattr(Settings(_env_file=None), name.lower()) == 1


@given(count=st.integers(min_value=1, max_value=10**9))
def test_any_count_from_one_up_is_accepted(count: int) -> None:
    settings = make_settings(max_upload_mb=count, max_concurrency=count)

    assert (settings.max_upload_mb, settings.max_concurrency) == (count, count)


@given(count=st.integers(max_value=0))
def test_any_count_below_one_is_rejected(count: int) -> None:
    with pytest.raises(ValidationError, match="max_upload_mb"):
        make_settings(max_upload_mb=count)
    with pytest.raises(ValidationError, match="max_concurrency"):
        make_settings(max_concurrency=count)


@given(backend=st.text().filter(lambda text: text not in {"mlx", "transformers"}))
def test_any_backend_but_the_two_known_ones_is_rejected(backend: str) -> None:
    with pytest.raises(ValidationError, match="vlm_backend"):
        make_settings(vlm_backend=backend)


def test_the_environment_beats_the_env_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("MAX_CONCURRENCY=3\nMAX_UPLOAD_MB=9\n", encoding="utf-8")
    monkeypatch.setenv("MAX_CONCURRENCY", "2")
    monkeypatch.delenv("MAX_UPLOAD_MB", raising=False)

    settings = Settings(_env_file=env_file)

    assert settings.max_concurrency == 2  # the environment wins
    assert settings.max_upload_mb == 9  # the file fills what the environment leaves out


def test_a_relative_models_path_stays_relative() -> None:
    assert make_settings(models_path="weights").models_path == Path("weights")


def test_every_env_example_key_is_a_setting_and_every_setting_has_a_key() -> None:
    """`extra="ignore"` lets a misspelled key (`MAX_UPLOAD_MBS`) through the equality test above."""
    text = ENV_EXAMPLE.read_text(encoding="utf-8")
    keys = set(re.findall(r"^#?\s*([A-Z][A-Z0-9_]*)=", text, re.MULTILINE))

    assert keys == {name.upper() for name in Settings.model_fields}


def test_the_service_refuses_to_start_on_an_invalid_model_setting(tmp_path: Path) -> None:
    """The README promises it. The process fails while reading settings, before it binds a port."""
    environment = {**os.environ, "VLM_BACKEND": "cuda", "HOST": "127.0.0.1", "PORT": "18765"}

    result = subprocess.run(  # this interpreter, fixed arguments
        [sys.executable, "-m", "formlens"],
        cwd=tmp_path,  # no .env here
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )

    assert result.returncode != 0
    assert "vlm_backend" in result.stderr


# --- ModelSettings: the two settings the service and the downloader share -------------------------


def test_settings_are_model_settings_with_the_same_two_fields_and_defaults() -> None:
    models = ModelSettings(_env_file=None)
    settings = Settings(_env_file=None)

    assert isinstance(settings, ModelSettings)
    assert set(ModelSettings.model_fields) == {"models_path", "vlm_backend"}
    assert (models.models_path, models.vlm_backend) == (Path("models"), "mlx")
    assert (settings.models_path, settings.vlm_backend) == (models.models_path, models.vlm_backend)


def test_model_settings_ignore_an_unrelated_bad_value_in_the_env_file(tmp_path: Path) -> None:
    """A `.env` with `PORT=abc` stops the service, but it must not stop `make download-models`."""
    env_file = tmp_path / ".env"
    env_file.write_text("PORT=abc\nVLM_BACKEND=transformers\nMODELS_PATH=weights\n", encoding="utf-8")

    models = ModelSettings(_env_file=env_file)

    assert (models.vlm_backend, models.models_path) == ("transformers", Path("weights"))
    with pytest.raises(ValidationError, match="port"):
        Settings(_env_file=env_file)


def test_model_settings_read_the_dot_env_of_the_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / ".env").write_text("VLM_BACKEND=transformers\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    assert ModelSettings().vlm_backend == "transformers"
    assert Settings().vlm_backend == "transformers"


def test_the_environment_beats_the_env_file_for_the_model_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / ".env").write_text("VLM_BACKEND=transformers\nMODELS_PATH=from-file\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("VLM_BACKEND", "mlx")

    models = ModelSettings()

    assert (models.vlm_backend, models.models_path) == ("mlx", Path("from-file"))


def test_model_settings_refuse_an_empty_models_path() -> None:
    with pytest.raises(ValidationError, match="must not be empty; unset it to use 'models'"):
        ModelSettings(_env_file=None, models_path="")  # type: ignore[arg-type]  # a text: the empty value must be refused


@pytest.mark.parametrize("backend", ["cuda", "MLX", "", " mlx"], ids=["unknown", "wrong-case", "empty", "padded"])
def test_model_settings_refuse_an_unknown_backend(backend: str) -> None:
    with pytest.raises(ValidationError, match="vlm_backend"):
        ModelSettings(_env_file=None, vlm_backend=backend)  # type: ignore[arg-type]  # the point of the test


# --- Extraction settings: database, model endpoint, job limits -------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:11434/v1",
        "http://127.0.0.1:11434/v1",
        "http://127.8.8.8/v1",
        "http://[::1]:11434/v1",
        "http://192.168.1.20:11434/v1",
        "http://10.0.0.5/v1",
        "http://172.16.4.4/v1",
        "http://ollama:11434/v1",
        "https://host.docker.internal:11434/v1",
    ],
    ids=[
        "localhost",
        "loopback",
        "loopback-range",
        "loopback-v6",
        "private-192",
        "private-10",
        "private-172",
        "dotless-service-name",
        "docker-host",
    ],
)
def test_the_model_endpoint_may_be_on_this_machine_or_its_private_network(url: str) -> None:
    assert make_settings(llm_base_url=url).llm_base_url == url


@pytest.mark.parametrize(
    "url",
    [
        "https://api.openai.com/v1",
        "http://example.com:11434/v1",
        "http://8.8.8.8/v1",
        "http://[2001:4860:4860::8888]/v1",
        "http://ollama.internal.example.org/v1",
        "http://host.docker.internal.evil.example/v1",
        "http://user:pass@localhost:11434/v1",
        "ftp://localhost/v1",
        "localhost:11434/v1",
        "http:///v1",
        "http://localhost:notaport/v1",
        "",
    ],
    ids=[
        "openai",
        "dotted-name",
        "public-ipv4",
        "public-ipv6",
        "dotted-internal",
        "docker-lookalike",
        "credentials",
        "scheme",
        "no-scheme",
        "no-host",
        "bad-port",
        "empty",
    ],
)
def test_a_model_endpoint_that_could_send_documents_elsewhere_is_refused(url: str) -> None:
    with pytest.raises(ValidationError, match="llm_base_url"):
        make_settings(llm_base_url=url)


@pytest.mark.parametrize(
    "url",
    ["postgresql://u@localhost/db", "mysql://localhost/db", "formlens.db", ""],
    ids=["postgres", "mysql", "bare-path", "empty"],
)
def test_only_a_sqlite_url_is_accepted_as_the_database(url: str) -> None:
    with pytest.raises(ValidationError, match="db_url"):
        make_settings(db_url=url)


@pytest.mark.parametrize(
    "url",
    ["sqlite:///./formlens.db", "sqlite:////data/formlens.db", "sqlite://"],
    ids=["relative", "absolute", "memory"],
)
def test_a_sqlite_url_is_accepted_as_the_database(url: str) -> None:
    assert make_settings(db_url=url).db_url == url


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("llm_model", ""),
        ("llm_timeout_seconds", 0),
        ("llm_max_input_chars", 0),
        ("result_ttl_hours", 0),
        ("job_timeout_seconds", 0),
        ("job_max_attempts", 0),
        ("job_poll_interval_seconds", 0),
        ("job_poll_interval_seconds", -1.0),
        ("queue_max_pending", 0),
    ],
    ids=["model", "llm-timeout", "max-input", "ttl", "job-timeout", "attempts", "poll-zero", "poll-negative", "queue"],
)
def test_an_invalid_job_or_model_value_is_rejected(field: str, value: object) -> None:
    with pytest.raises(ValidationError, match=field):
        make_settings(**{field: value})


def test_the_job_timeout_must_exceed_the_parse_timeout() -> None:
    with pytest.raises(ValidationError, match="job_timeout_seconds must be greater than parse_timeout_seconds"):
        make_settings(parse_timeout_seconds=300, job_timeout_seconds=300)

    assert (
        make_settings(parse_timeout_seconds=300, job_timeout_seconds=301, llm_timeout_seconds=100).job_timeout_seconds
        == 301
    )


def test_the_model_timeout_must_stay_below_the_job_timeout() -> None:
    with pytest.raises(ValidationError, match="llm_timeout_seconds must be less than job_timeout_seconds"):
        make_settings(llm_timeout_seconds=600, job_timeout_seconds=600)

    assert make_settings(llm_timeout_seconds=599, job_timeout_seconds=600).llm_timeout_seconds == 599


@pytest.mark.parametrize(
    "url",
    [
        "http://134744072:11434/v1",
        "http://0x08080808/v1",
        "http://010.010.010.010/v1",
        "http://0x7f.1/v1",
        "http://127.1/v1",
        "http://2130706433/v1",
        "http://169.254.169.254/latest/meta-data",
        "http://[fe80::1]/v1",
        "http://0.0.0.0:11434/v1",
        "http://[::]:11434/v1",
        "http://[::ffff:8.8.8.8]/v1",
        "http://[::ffff:169.254.169.254]/v1",
        "http://8.8.8.8./v1",
        "http://my_host!/v1",
    ],
    ids=[
        "decimal",
        "hex",
        "octal",
        "hex-short",
        "short-dotted-loopback",
        "decimal-loopback",
        "link-local-metadata",
        "link-local-v6",
        "unspecified",
        "unspecified-v6",
        "mapped-public",
        "mapped-link-local",
        "trailing-dot",
        "odd-name",
    ],
)
def test_an_address_written_in_a_shorthand_or_that_is_link_local_is_refused(url: str) -> None:
    with pytest.raises(ValidationError, match="llm_base_url"):
        make_settings(llm_base_url=url)


@pytest.mark.parametrize(
    "url",
    [
        "http://[::ffff:10.0.0.1]/v1",
        "http://[::ffff:127.0.0.1]/v1",
        "http://[fd12:3456::1]/v1",
        "http://localhost/v1",
        "http://ollama-gpu_1:11434/v1",
        "http://host.docker.internal/v1",
        "http://192.168.0.7/v1",
    ],
    ids=["mapped-private", "mapped-loopback", "unique-local-v6", "localhost", "service-name", "docker-host", "private"],
)
def test_a_private_address_in_its_standard_form_and_a_plain_name_are_still_accepted(url: str) -> None:
    assert make_settings(llm_base_url=url).llm_base_url == url


# --- LlmSettings: the two settings the service, `make evaluate` and the slow tests share ------------


def test_settings_are_llm_settings_with_the_same_two_fields_and_defaults() -> None:
    llm = LlmSettings(_env_file=None)
    settings = Settings(_env_file=None)

    assert isinstance(settings, LlmSettings)
    assert set(LlmSettings.model_fields) == {"llm_base_url", "llm_model"}
    assert (llm.llm_base_url, llm.llm_model) == ("http://localhost:11434/v1", "qwen3:8b")
    assert (settings.llm_base_url, settings.llm_model) == (llm.llm_base_url, llm.llm_model)


def test_llm_settings_ignore_an_unrelated_bad_value_in_the_env_file(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("PORT=abc\nLLM_MODEL=other:1b\n", encoding="utf-8")

    assert LlmSettings(_env_file=env_file).llm_model == "other:1b"
    with pytest.raises(ValidationError, match="port"):
        Settings(_env_file=env_file)


def test_llm_settings_refuse_an_address_that_is_not_local() -> None:
    with pytest.raises(ValidationError, match="llm_base_url"):
        LlmSettings(_env_file=None, llm_base_url="http://8.8.8.8/v1")


def test_the_slow_tests_read_the_language_model_from_the_env_file_like_make_evaluate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`make test-models` and `make evaluate` must use the model that `.env` names, not each their own."""
    (tmp_path / ".env").write_text(
        "LLM_MODEL=from-the-file:1b\nLLM_BASE_URL=http://ollama:11434/v1\n", encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)

    settings = slow_settings()

    assert (settings.llm_model, settings.llm_base_url) == ("from-the-file:1b", "http://ollama:11434/v1")
    assert Settings().llm_model == settings.llm_model  # what the service and `make evaluate` read


def test_the_environment_beats_the_env_file_for_the_llm_settings_of_the_slow_tests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / ".env").write_text("LLM_MODEL=from-the-file:1b\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("LLM_MODEL", "from-the-shell:2b")

    assert slow_settings().llm_model == "from-the-shell:2b"


def test_the_json_body_limit_defaults_to_256_kb_and_must_be_at_least_one() -> None:
    assert Settings(_env_file=None).max_json_body_kb == 256
    with pytest.raises(ValidationError, match="max_json_body_kb"):
        make_settings(max_json_body_kb=0)
