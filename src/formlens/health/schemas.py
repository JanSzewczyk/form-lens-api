"""Response models of the health endpoints."""

from typing import Literal

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    """Liveness probe payload."""

    status: Literal["ok"] = Field(
        default="ok", description="Always `ok` while the process can answer.", examples=["ok"]
    )


class ReadinessResponse(BaseModel):
    """Readiness probe payload."""

    status: Literal["ready"] = Field(default="ready", description="Every readiness check passed.", examples=["ready"])
    checks: dict[str, Literal["ok"]] = Field(
        description="Name of each registered check with its result.",
        examples=[{"storage": "ok"}],
    )
