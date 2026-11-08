"""Application settings loaded from environment variables."""

from typing import Literal, cast

from fastapi import Request
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

type Environment = Literal["local", "test", "production"]
type LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
type LogFormat = Literal["auto", "json", "console"]


class Settings(BaseSettings):
    """Runtime configuration, read from the environment or a local `.env` file.

    Tests build it with `Settings(_env_file=None, ...)` so a developer's `.env` never leaks in.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = Field(default="fastapi-szumplate", description="Title shown in the API docs.")
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
    loans_max_active_per_member: int = Field(
        default=3, ge=1, description="Example domain: active loans one member may hold."
    )
    loan_days: int = Field(default=14, ge=1, description="Example domain: days between borrowing and the due date.")

    @property
    def resolved_log_format(self) -> Literal["json", "console"]:
        """Return the concrete log format, resolving `auto` from the environment."""
        if self.log_format != "auto":
            return self.log_format
        return "console" if self.environment == "local" else "json"


def get_settings(request: Request) -> Settings:
    """Return the settings the running app was built with."""
    return cast("Settings", request.app.state.settings)
