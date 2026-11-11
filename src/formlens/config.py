"""Application settings loaded from environment variables."""

import ipaddress
import re
import socket
from pathlib import Path
from typing import Final, Literal, Self, cast
from urllib.parse import urlsplit

from fastapi import Request
from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from formlens.modelspec import VlmBackend

type Environment = Literal["local", "test", "production"]
type LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
type LogFormat = Literal["auto", "json", "console"]

# A name that reaches the model server from inside a container; it has dots, so it is listed.
_DOCKER_HOST: Final = "host.docker.internal"


_NAME: Final = re.compile(r"[a-z0-9_-]+")


def _is_ipv4_shorthand(host: str) -> bool:
    """Tell whether the C resolver would read `host` as an IPv4 address in a form `ipaddress` does not accept.

    `inet_aton` takes `134744072` and `0x08080808` (both are 8.8.8.8), `127.1` and the octal `010.010.010.010`. A
    client library hands the string to the resolver, which reads it that way, so such a host is refused instead
    of being read as the name it looks like.
    """
    try:
        socket.inet_aton(host)
    except OSError:
        return False
    return True


def is_local_host(host: str) -> bool:
    """Tell whether `host` is a machine of the operator's own: loopback, a private address or a plain name.

    A document is sent to this host, so it must not be somebody else's server. Accepted: an IP address in its
    standard form (dotted IPv4 or IPv6) that is loopback or private, a name without a dot (`localhost`, a Compose
    service such as `ollama`) and `host.docker.internal`. Refused: any other dotted name, every shorthand or
    numeric spelling of an address, link-local (169.254.0.0/16, fe80::/10, where cloud metadata lives) and
    unspecified addresses. A dotless name is **trusted to resolve locally**: nothing here asks a resolver.
    """
    if host == _DOCKER_HOST:
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return not _is_ipv4_shorthand(host) and _NAME.fullmatch(host) is not None
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped  # ::ffff:8.8.8.8 is 8.8.8.8
    if address.is_link_local or address.is_unspecified:
        return False
    return address.is_loopback or address.is_private


def require_local_model_url(value: str) -> str:
    """Return `value` if it is an http(s) URL of a local model server, else raise `ValueError`.

    The settings call it, and so does the model client when it is built, so a client made by hand with
    another URL is refused too: a document must not be sent to somebody else's server.
    """
    try:
        parts = urlsplit(value)
        host = parts.hostname
        _ = parts.port  # a port that is not a number raises here
    except ValueError as exc:
        msg = "must be an http(s) URL with a host, for example http://localhost:11434/v1"
        raise ValueError(msg) from exc
    if parts.scheme not in {"http", "https"} or not host:
        msg = "must be an http(s) URL with a host, for example http://localhost:11434/v1"
        raise ValueError(msg)
    if parts.username is not None or parts.password is not None:
        msg = "must not contain a user name or password"
        raise ValueError(msg)
    if not is_local_host(host):
        msg = (
            "must point to a loopback or private address in its standard form, a name without a dot or "
            "host.docker.internal"
        )
        raise ValueError(msg)
    return value


class ModelSettings(BaseSettings):
    """Where the document model lives and which backend runs it.

    The service and `scripts/resolve_model.py` (behind `make download-models`) both read these two
    settings, so a `.env` moves the download and the service together. It holds no other setting, so
    an unrelated bad value in `.env` (`PORT=abc`) cannot block a download.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    models_path: Path = Field(
        default=Path("models"),
        description=(
            "Folder with the downloaded document models; a relative path is read from the working directory. "
            "An empty value is refused."
        ),
    )
    vlm_backend: VlmBackend = Field(
        default="mlx",
        description=(
            "Inference backend of the document model: `mlx` (the backend this project uses on Apple Silicon) "
            "or `transformers`."
        ),
    )

    @field_validator("models_path", mode="before")
    @classmethod
    def _refuse_an_empty_models_path(cls, value: object) -> object:
        """Refuse `MODELS_PATH=`: `Path("")` is the working directory, which no one means by an empty value."""
        if isinstance(value, str) and value == "":
            msg = "must not be empty; unset it to use 'models'"
            raise ValueError(msg)
        return value


class LlmSettings(BaseSettings):
    """Which language model the service talks to and where it runs.

    The service, `make evaluate` and the `slow` tests all read these two settings through this class, so a `.env`
    moves them together; it holds no other setting, so an unrelated bad value in `.env` cannot stop it.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    llm_base_url: str = Field(
        default="http://localhost:11434/v1",
        description=(
            "OpenAI-compatible endpoint of the local language model (Ollama). The documents are sent there, so "
            "only a loopback or private address, a name without a dot or `host.docker.internal` is accepted."
        ),
    )
    llm_model: str = Field(
        default="qwen3:8b", min_length=1, description="Name of the language model that reads the parsed text."
    )

    @field_validator("llm_base_url")
    @classmethod
    def _require_a_local_model_server(cls, value: str) -> str:
        """Refuse an endpoint that is not on this machine or its private network, and a URL with credentials."""
        return require_local_model_url(value)


class Settings(ModelSettings, LlmSettings):
    """Runtime configuration, read from the environment or a local `.env` file.

    Tests build it with `Settings(_env_file=None, ...)` so a developer's `.env` never leaks in.
    """

    app_name: str = Field(default="formlens", description="Title shown in the API docs.")
    environment: Environment = Field(
        default="local", description="Deployment environment; `auto` log format follows it."
    )

    log_level: LogLevel = Field(default="INFO", description="Minimum level that is logged.")
    log_format: LogFormat = Field(
        default="auto",
        description="`json` or `console`; `auto` picks `console` locally and `json` elsewhere.",
    )

    docs_enabled: bool = Field(
        default=False,
        description="Serve /docs, /redoc and /openapi.json. Keep off on a public API.",
    )
    cors_origins: list[str] = Field(
        default_factory=list,
        description="Allowed CORS origins as a JSON list. Empty disables CORS entirely.",
    )

    host: str = Field(default="127.0.0.1", description="Interface the server binds to.")
    port: int = Field(default=8000, ge=1, le=65535, description="Port the server listens on.")
    reload: bool = Field(default=False, description="Restart the server on code changes.")
    graceful_shutdown_seconds: int = Field(
        default=20,
        ge=0,
        description="Seconds open requests get to finish after SIGTERM; keep below the orchestrator's grace period.",
    )

    default_page_size: int = Field(
        default=20, ge=1, le=100, description="Page size when a list request gives no limit."
    )

    max_upload_mb: int = Field(default=25, ge=1, description="Largest accepted upload, in megabytes.")
    max_json_body_kb: int = Field(
        default=256,
        ge=1,
        description=(
            "Largest accepted JSON request body of the template routes, in kilobytes; a larger one is refused with "
            "413 `body-too-large` before it is read."
        ),
    )
    max_concurrency: int = Field(
        default=1, ge=1, description="Documents converted at the same time; the model is heavy, so keep it low."
    )
    parse_timeout_seconds: int = Field(
        default=300,
        ge=1,
        description="Seconds one document may take to parse before the request fails with 500 `parse-failed`.",
    )

    db_url: str = Field(
        default="sqlite:///./formlens.db",
        description=(
            "SQLAlchemy URL of the database. Only SQLite is supported; a relative file is read from the "
            "working directory. Run `make migrate` after changing it."
        ),
    )

    llm_timeout_seconds: int = Field(
        default=120, ge=1, description="Seconds one call to the language model may take; below the job timeout."
    )
    llm_max_input_chars: int = Field(
        default=20000, ge=1, description="Longest document text sent to the model, in characters; a longer one fails."
    )

    result_ttl_hours: int = Field(
        default=24, ge=1, description="Hours a finished extraction stays readable before it is deleted."
    )
    job_timeout_seconds: int = Field(
        default=600,
        ge=1,
        description="Seconds one extraction job may run, from claim to result; above the parse timeout.",
    )
    job_max_attempts: int = Field(
        default=2, ge=1, description="Times a job is started before it fails; 2 lets a restart run it again."
    )
    job_poll_interval_seconds: float = Field(
        default=2.0, gt=0, description="Seconds the worker waits before it looks for a job again when idle."
    )
    queue_max_pending: int = Field(
        default=100, ge=1, description="Extractions that may wait at once; one more is refused with 503."
    )

    @field_validator("db_url")
    @classmethod
    def _require_sqlite(cls, value: str) -> str:
        """Refuse a URL of another database: the transactions and the migrations are written for SQLite."""
        if not value.startswith("sqlite:"):
            msg = "must be a sqlite: URL, for example sqlite:///./formlens.db"
            raise ValueError(msg)
        return value

    @model_validator(mode="after")
    def _order_the_timeouts(self) -> Self:
        """Keep the timeouts nested: parse < job, and the model call < job."""
        if self.job_timeout_seconds <= self.parse_timeout_seconds:
            msg = "job_timeout_seconds must be greater than parse_timeout_seconds"
            raise ValueError(msg)
        if self.llm_timeout_seconds >= self.job_timeout_seconds:
            msg = "llm_timeout_seconds must be less than job_timeout_seconds"
            raise ValueError(msg)
        return self

    @property
    def resolved_log_format(self) -> Literal["json", "console"]:
        """Return the concrete log format, resolving `auto` from the environment."""
        if self.log_format != "auto":
            return self.log_format
        return "console" if self.environment == "local" else "json"


def get_settings(request: Request) -> Settings:
    """Return the settings the running app was built with."""
    return cast("Settings", request.app.state.settings)
