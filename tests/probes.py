"""Routes that exist only in tests, so the core is tested without any domain module.

Add them before the first request: `_allowed_methods` reads `app.openapi()`, which is cached.
"""

from typing import Annotated

from fastapi import FastAPI, HTTPException, Path, Query
from pydantic import BaseModel, ConfigDict, Field

from formlens.problems import ProblemType, domain_error_handler


class Payload(BaseModel):
    """A body with a bounded string, so a rejected value can be checked for echoing."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=10)


class Refused(Exception):
    """Probe domain error."""


REFUSED = ProblemType("probe-refused", "Probe refused", 409)


def add_probe_routes(app: FastAPI) -> FastAPI:
    """Mount the probe routes on `app` and return it."""

    @app.get("/probe/thing", operation_id="get_probe_thing")
    def get_thing() -> dict[str, str]:
        return {}

    @app.put("/probe/thing", operation_id="put_probe_thing")
    def put_thing() -> dict[str, str]:
        return {}

    @app.get("/probe/limit", operation_id="get_probe_limit")
    def limited(limit: Annotated[int, Query(le=100)]) -> dict[str, int]:
        return {"limit": limit}

    @app.get("/probe/tags", operation_id="get_probe_tags")
    def tags(
        tag: Annotated[list[str] | None, Query()] = None,
        colour: Annotated[str | None, Query()] = None,
    ) -> dict[str, list[str] | str | None]:
        return {"tag": tag, "colour": colour}

    @app.get("/probe/items/{item_id}", operation_id="get_probe_item")
    def get_item(item_id: Annotated[int, Path()]) -> dict[str, int]:
        return {"item_id": item_id}

    @app.post("/probe/body", operation_id="post_probe_body")
    def post_body(payload: Payload) -> dict[str, str]:
        return {"name": payload.name}

    @app.get("/probe/boom", operation_id="get_probe_boom")
    def boom() -> None:
        raise RuntimeError("internal detail that must not leak")

    @app.get("/probe/auth", operation_id="get_probe_auth")
    def auth() -> None:
        raise HTTPException(401, "Bearer token required", headers={"WWW-Authenticate": "Bearer"})

    @app.get("/probe/convert", operation_id="get_probe_convert")
    def convert(value: str) -> int:
        try:
            return int(value)
        except ValueError as err:
            raise HTTPException(400, "value must be an integer") from err

    @app.get("/probe/refused", operation_id="get_probe_refused")
    def refused() -> None:
        raise Refused("not today")

    app.add_exception_handler(Refused, domain_error_handler({Refused: REFUSED}))
    return app
