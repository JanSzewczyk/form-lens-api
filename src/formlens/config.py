"""Application settings loaded from environment variables."""

from pathlib import Path
from typing import Literal, cast

from fastapi import Request
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from formlens.modelspec import VlmBackend

type Environment = Literal["local", "test", "production"]
type LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
type LogFormat = Literal["auto", "json", "console"]


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


class Settings(ModelSettings):
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
    max_concurrency: int = Field(
        default=1, ge=1, description="Documents converted at the same time; the model is heavy, so keep it low."
    )
    parse_timeout_seconds: int = Field(
        default=300,
        ge=1,
        description="Seconds one document may take to parse before the request fails with 500 `parse-failed`.",
    )

    @property
    def resolved_log_format(self) -> Literal["json", "console"]:
        """Return the concrete log format, resolving `auto` from the environment."""
        if self.log_format != "auto":
            return self.log_format
        return "console" if self.environment == "local" else "json"


def get_settings(request: Request) -> Settings:
    """Return the settings the running app was built with."""
    return cast("Settings", request.app.state.settings)
