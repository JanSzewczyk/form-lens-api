"""Query parameters that arrive more than once."""

from typing import Any, Final, cast

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError

REPEATED_PARAMETER: Final = "repeated_parameter"


def _is_array(schema: dict[str, Any]) -> bool:
    """Tell whether a parameter schema accepts a list, also as one branch of `anyOf`."""
    return schema.get("type") == "array" or any(_is_array(s) for s in schema.get("anyOf", []))


def _scalar_query_parameters(request: Request) -> list[str]:
    """Name the query parameters of the matched operation that take one value.

    The names come from the generated OpenAPI document, so the rule is the one the spec states.
    A route with `include_in_schema=False` is not in that document and keeps Starlette's
    "last value wins" behaviour.
    """
    path = getattr(request.scope.get("route"), "path_format", None)
    app = cast("FastAPI", request.app)
    operation = app.openapi().get("paths", {}).get(path, {}).get(request.method.lower(), {})
    return [
        parameter["name"]
        for parameter in operation.get("parameters", [])
        if parameter.get("in") == "query" and not _is_array(parameter.get("schema", {}))
    ]


def reject_repeated_query_parameters(request: Request) -> None:
    """Answer 422 when a query parameter that takes one value is given more than once.

    Starlette keeps the last of several values, so `?offset=1&offset=oops` would be read as
    `oops` and `?offset=oops&offset=1` as `1`: the same request means two things. The spec says
    the parameter is a single value, so the request is invalid. The value is never echoed.
    """
    repeated = [name for name in _scalar_query_parameters(request) if len(request.query_params.getlist(name)) > 1]
    if repeated:
        raise RequestValidationError(
            [
                {
                    "type": REPEATED_PARAMETER,
                    "loc": ("query", name),
                    "msg": "Give this query parameter once.",
                    "input": None,
                }
                for name in repeated
            ]
        )
