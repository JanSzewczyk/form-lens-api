"""Health check endpoints."""

from collections.abc import Mapping
from typing import Annotated

from fastapi import APIRouter, Depends

from fastapi_szumplate.health.readiness import (
    SERVICE_NOT_READY,
    ReadinessCheck,
    get_readiness_checks,
    run_checks,
)
from fastapi_szumplate.health.schemas import HealthResponse, ReadinessResponse
from fastapi_szumplate.problems import problem_response

router = APIRouter(tags=["health"])


@router.get("/health", operation_id="get_health")
def get_health() -> HealthResponse:
    """Report that the service is alive.

    The probe answers without touching any dependency; use it for liveness.
    """
    return HealthResponse()


@router.get(
    "/health/ready",
    operation_id="get_readiness",
    responses={503: problem_response(SERVICE_NOT_READY)},
)
def get_readiness(
    checks: Annotated[Mapping[str, ReadinessCheck], Depends(get_readiness_checks)],
) -> ReadinessResponse:
    """Report whether the service can take traffic.

    Runs every registered readiness check. A failed check answers 503 and names the check, not
    the error; the error is in the server log. Use it for readiness, not liveness.
    """
    return ReadinessResponse.model_validate({"checks": run_checks(checks)})
