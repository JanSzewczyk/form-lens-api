"""Problem Details (RFC 9457): one error model and the handlers that produce it."""

import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from http import HTTPStatus
from typing import Any, Final, cast

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.utils import is_body_allowed_for_status_code
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import JSONResponse, Response

PROBLEM_MEDIA_TYPE: Final = "application/problem+json"
PROBLEM_TYPE_PREFIX: Final = "urn:problem:formlens:"
_HTTP_METHODS: Final = frozenset({"get", "put", "post", "delete", "patch", "head", "options"})
_UNHANDLED_DETAIL: Final = "The server failed to process the request."
_FASTAPI_BODY_PARSE_DETAIL: Final = "There was an error parsing the body"  # fastapi/routing.py

log = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ProblemType:
    """A machine-readable kind of error: a stable slug, a stable title and its HTTP status."""

    slug: str
    title: str
    status: int

    @property
    def type(self) -> str:
        """Return the `type` URI clients branch on."""
        return f"{PROBLEM_TYPE_PREFIX}{self.slug}"


VALIDATION_ERROR: Final = ProblemType("validation-error", "Request validation failed", 422)


class ValidationIssue(BaseModel):
    """One rejected input value, without the value itself."""

    loc: list[str | int] = Field(
        description="Where the problem is: `body`, `query`, `path` or `header`, then the field.",
        examples=[["query", "limit"]],
    )
    msg: str = Field(description="What is wrong.", examples=["Input should be less than or equal to 100"])
    type: str = Field(description="Pydantic error code.", examples=["less_than_equal"])


class ProblemDetail(BaseModel):
    """The one error shape every endpoint returns (RFC 9457)."""

    type: str = Field(
        default="about:blank",
        description="URI that identifies the kind of problem; clients branch on it.",
        examples=["urn:problem:formlens:validation-error"],
    )
    title: str = Field(description="Short, stable summary of the kind.", examples=["Not Found"])
    status: int = Field(description="HTTP status code.", examples=[404])
    detail: str | None = Field(
        default=None,
        description="Explanation of this occurrence. Do not parse it.",
        examples=["The resource does not exist."],
    )
    errors: list[ValidationIssue] | None = Field(
        default=None, description="Rejected inputs; present on validation errors only."
    )
    request_id: str | None = Field(
        default=None,
        description="Value of the X-Request-ID response header, to quote when asking for support.",
        examples=["0192f5e0-5a3b-7c11-9d2e-3f6a1b2c4d5e"],
    )


def problem_response(*types: ProblemType, description: str | None = None) -> dict[str, Any]:
    """Build a `responses` entry for an error status.

    The description lists the problem types the status can carry, so the spec documents each one.
    """
    if description is None:
        description = "; ".join(f"{t.title} (`{t.slug}`)" for t in types) or "Error"
    return {
        "model": ProblemDetail,
        "description": description,
        "content": {PROBLEM_MEDIA_TYPE: {}},
    }


def malformed_body_response() -> dict[str, Any]:
    """Build the `responses` entry for a body that cannot be read at all.

    Starlette answers 400 when the bytes are not decodable text (for example invalid UTF-8);
    a body that is text but not JSON is a 422 `json_invalid`.
    """
    return problem_response(description="The request body could not be read as text.")


def register_problem_types(app: FastAPI, *types: ProblemType) -> None:
    """Record the problem types an app can answer with, so tests can check they are documented."""
    existing: list[ProblemType] = getattr(app.state, "problem_types", [])
    app.state.problem_types = [*existing, *(t for t in dict.fromkeys(types) if t not in existing)]


def problem(
    request: Request,
    *,
    status: int,
    title: str,
    detail: str | None = None,
    type_: str = "about:blank",
    errors: list[ValidationIssue] | None = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    """Render a Problem Details response, carrying the request id when one is bound."""
    body = ProblemDetail(
        type=type_,
        title=title,
        status=status,
        detail=detail,
        errors=errors,
        request_id=request.scope.get("state", {}).get("request_id"),
    )
    return JSONResponse(
        body.model_dump(mode="json", exclude_none=True),
        status_code=status,
        media_type=PROBLEM_MEDIA_TYPE,
        headers=dict(headers) if headers else None,
    )


def domain_error_handler(
    mapping: Mapping[type[Exception], ProblemType],
) -> Callable[[Request, Exception], Awaitable[Response]]:
    """Build the one handler a domain registers for its exceptions.

    The mapping keeps domain exceptions free of HTTP: the domain raises, this turns it into a
    problem with its own type. A refusal is expected, so it is a warning without a traceback.
    """

    async def handle(request: Request, exc: Exception) -> Response:
        kind = next(mapping[cls] for cls in type(exc).__mro__ if cls in mapping)
        log.warning("request_refused", problem=kind.slug, status=kind.status)
        return problem(request, status=kind.status, title=kind.title, detail=str(exc), type_=kind.type)

    return handle


def register_domain_errors(app: FastAPI, mapping: Mapping[type[Exception], ProblemType]) -> None:
    """Handle a domain's exceptions with one handler and record their problem types."""
    handler = domain_error_handler(mapping)
    for exception_type in mapping:
        app.add_exception_handler(exception_type, handler)
    register_problem_types(app, *dict.fromkeys(mapping.values()))


def _allowed_methods(request: Request) -> list[str]:
    """Read the methods of every OpenAPI path that matches, not only the first matching route."""
    methods: set[str] = set()
    for template, item in request.app.openapi().get("paths", {}).items():
        segments = ("[^/]+" if segment.startswith("{") else re.escape(segment) for segment in template.split("/"))
        if re.fullmatch("/".join(segments), request.url.path):
            methods.update(m.upper() for m in item if m in _HTTP_METHODS)
    return sorted(methods)


def _validation_problem(request: Request, issues: list[ValidationIssue]) -> JSONResponse:
    return problem(
        request,
        status=VALIDATION_ERROR.status,
        title=VALIDATION_ERROR.title,
        detail="One or more inputs are invalid.",
        type_=VALIDATION_ERROR.type,
        errors=issues,
    )


def _is_unreadable_json_value(exc: StarletteHTTPException) -> bool:
    """Tell FastAPI's 400 for a JSON number it cannot parse from any other 400.

    FastAPI answers 400 with its own detail for any non-`JSONDecodeError` raised while it parses
    a body. For valid JSON that is a plain `ValueError` from `json` (an integer of more than 4300
    digits); invalid UTF-8 is a `UnicodeDecodeError`, which stays a 400 because the bytes are not
    text. A 400 that application code raises keeps its own detail, even when it was raised from a
    `ValueError`, so the detail FastAPI uses is part of the test.
    """
    cause = exc.__cause__
    return (
        exc.status_code == HTTPStatus.BAD_REQUEST
        and exc.detail == _FASTAPI_BODY_PARSE_DETAIL
        and isinstance(cause, ValueError)
        and not isinstance(cause, UnicodeDecodeError)
    )


def _status_title(status: int) -> str:
    """Return the reason phrase of a status, or a generic title for a code `http` does not know."""
    try:
        return HTTPStatus(status).phrase
    except ValueError:
        return "Error"


async def _http_exception_handler(request: Request, exc: Exception) -> Response:
    """Answer an `HTTPException` with a problem.

    A status that forbids content (1xx, 204, 205, 304) gets no body. A `detail` that is not text is
    left out: data a client needs belongs in a `ProblemType`, not in a stringified structure.
    """
    http_exc = cast("StarletteHTTPException", exc)
    if _is_unreadable_json_value(http_exc):
        issue = ValidationIssue(loc=["body"], msg="JSON contains an integer with too many digits", type="json_invalid")
        return _validation_problem(request, [issue])
    headers = dict(http_exc.headers or {})
    if not is_body_allowed_for_status_code(http_exc.status_code):
        return Response(status_code=http_exc.status_code, headers=headers)
    if http_exc.status_code == HTTPStatus.METHOD_NOT_ALLOWED:
        allowed = _allowed_methods(request)
        if allowed:
            headers["Allow"] = ", ".join(allowed)
    detail: object = http_exc.detail  # Starlette types it `str`; FastAPI's subclass accepts anything
    return problem(
        request,
        status=http_exc.status_code,
        title=_status_title(http_exc.status_code),
        detail=detail if isinstance(detail, str) else None,
        headers=headers,
    )


async def _validation_exception_handler(request: Request, exc: Exception) -> Response:
    validation_exc = cast("RequestValidationError", exc)
    issues = [ValidationIssue(loc=list(e["loc"]), msg=e["msg"], type=e["type"]) for e in validation_exc.errors()]
    return _validation_problem(request, issues)


def unhandled_problem(request: Request) -> JSONResponse:
    """Build the generic 500 problem: fixed text, nothing from the exception."""
    return problem(
        request,
        status=500,
        title=HTTPStatus.INTERNAL_SERVER_ERROR.phrase,
        detail=_UNHANDLED_DETAIL,
    )


async def _backstop_exception_handler(request: Request, _exc: Exception) -> Response:
    return unhandled_problem(request)


def add_problem_handlers(app: FastAPI) -> None:
    """Make every error the framework raises itself answer with Problem Details.

    An exception without a handler is answered by `UnhandledErrorMiddleware`, so that the answer
    passes through the other middleware. The `Exception` handler below runs outside all of them:
    it is the backstop for a failure in the middleware themselves, and its response has no
    `X-Request-ID` header and no CORS headers. The server logs that traceback.
    """
    app.add_exception_handler(StarletteHTTPException, _http_exception_handler)
    app.add_exception_handler(RequestValidationError, _validation_exception_handler)
    app.add_exception_handler(Exception, _backstop_exception_handler)
    register_problem_types(app, VALIDATION_ERROR)
