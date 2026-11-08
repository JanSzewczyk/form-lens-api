"""OpenAPI metadata and the one post-processing step the generated document needs."""

from typing import Any, Final

from fastapi import FastAPI

from formlens import __version__
from formlens.problems import PROBLEM_MEDIA_TYPE

DESCRIPTION: Final = """\
FormLens API: extracts structured data from forms with a document model that runs locally.

Every error is returned as Problem Details (RFC 9457, `application/problem+json`). Branch on the
`type` field, never on `detail`. Every response carries an `X-Request-ID` header; quote it when
you report a problem.
"""

METADATA: Final[dict[str, Any]] = {
    "version": __version__,
    "description": DESCRIPTION,
    "contact": {"name": "Szum-Tech", "url": "https://github.com/JanSzewczyk/form-lens-api"},
    "license_info": {"name": "Proprietary (all rights reserved)"},
    # Relative, so "Try it out" calls the host that serves the docs, wherever it runs.
    "servers": [{"url": "/", "description": "The host that serves this document"}],
}

HEALTH_TAG: Final = {
    "name": "health",
    "description": "Liveness and readiness probes. Not versioned.",
}

_SCHEMAS_TO_DROP: Final = ("HTTPValidationError", "ValidationError")


def add_tags(app: FastAPI, *tags: dict[str, Any]) -> None:
    """Append tag descriptions to the app before its OpenAPI document is generated."""
    app.openapi_tags = [*(app.openapi_tags or []), *tags]


def _move_error_schemas_to_problem_media_type(schema: dict[str, Any]) -> None:
    for operations in schema.get("paths", {}).values():
        for operation in operations.values():
            for status, response in operation.get("responses", {}).items():
                if not (status.startswith(("4", "5")) or status == "default"):
                    continue
                content = response.get("content", {})
                plain = content.pop("application/json", None)
                if plain is not None:
                    content.setdefault(PROBLEM_MEDIA_TYPE, {}).setdefault("schema", plain["schema"])


def install_openapi(app: FastAPI) -> None:
    """Replace `app.openapi` with a cached version that documents errors as problem+json only.

    FastAPI lists an error model under `application/json` next to the problem media type and
    adds its own validation schemas; the service never sends either, so they are removed.
    """
    original = app.openapi

    def openapi() -> dict[str, Any]:
        if app.openapi_schema is None:
            schema = original()
            _move_error_schemas_to_problem_media_type(schema)
            for name in _SCHEMAS_TO_DROP:
                schema.get("components", {}).get("schemas", {}).pop(name, None)
        return app.openapi_schema or {}

    app.openapi = openapi  # type: ignore[method-assign]  # documented FastAPI extension point
