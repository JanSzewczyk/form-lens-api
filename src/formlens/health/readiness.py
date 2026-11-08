"""Readiness checks: a registry of callables that raise when a dependency is unavailable."""

from collections.abc import Callable, Mapping
from typing import cast

import structlog
from fastapi import FastAPI, Request

from formlens.problems import ProblemType, register_domain_errors

type ReadinessCheck = Callable[[], None]

SERVICE_NOT_READY = ProblemType("service-not-ready", "Service not ready", 503)

log = structlog.get_logger(__name__)


class ServiceNotReady(Exception):
    """At least one readiness check failed."""


def install_readiness(app: FastAPI) -> None:
    """Create the empty check registry and map `ServiceNotReady` to its problem type."""
    app.state.readiness_checks = {}
    register_domain_errors(app, {ServiceNotReady: SERVICE_NOT_READY})


def register_readiness_check(app: FastAPI, name: str, check: ReadinessCheck) -> None:
    """Add a check; it must raise any exception when its dependency is unavailable."""
    cast("dict[str, ReadinessCheck]", app.state.readiness_checks)[name] = check


def get_readiness_checks(request: Request) -> Mapping[str, ReadinessCheck]:
    """Return the checks registered on the running app."""
    return cast("Mapping[str, ReadinessCheck]", request.app.state.readiness_checks)


def run_checks(checks: Mapping[str, ReadinessCheck]) -> dict[str, str]:
    """Run every check, then raise `ServiceNotReady` naming the failed ones (never the errors)."""
    failed: list[str] = []
    for name, check in checks.items():
        try:
            check()
        except Exception:
            log.exception("readiness_check_failed", check=name)
            failed.append(name)
    if failed:
        raise ServiceNotReady("Not ready: " + ", ".join(sorted(failed)))
    return dict.fromkeys(checks, "ok")
