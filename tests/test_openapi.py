"""Contract tests over the generated OpenAPI document of the whole app."""

import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute, iter_route_contexts
from fastapi.testclient import TestClient

from formlens.main import create_app
from formlens.openapi import add_tags, install_openapi
from formlens.problems import PROBLEM_MEDIA_TYPE, VALIDATION_ERROR
from tests.conftest import make_settings
from tests.probes import add_probe_routes

HTTP_METHODS = {"get", "put", "post", "delete", "patch", "head", "options"}


@pytest.fixture
def spec(app: FastAPI) -> dict[str, Any]:
    return app.openapi()


def operations(spec: dict[str, Any]) -> list[tuple[str, str, dict[str, Any]]]:
    return [
        (method.upper(), path, operation)
        for path, item in spec["paths"].items()
        for method, operation in item.items()
        if method in HTTP_METHODS
    ]


def error_responses(spec: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    return [
        (f"{method} {path} {status}", response)
        for method, path, operation in operations(spec)
        for status, response in operation["responses"].items()
        if status[0] in "45"
    ]


def test_no_error_response_offers_application_json(spec: dict[str, Any]) -> None:
    for where, response in error_responses(spec):
        assert set(response["content"]) == {PROBLEM_MEDIA_TYPE}, where


def test_every_error_response_uses_the_problem_detail_schema(spec: dict[str, Any]) -> None:
    for where, response in error_responses(spec):
        schema = response["content"][PROBLEM_MEDIA_TYPE]["schema"]
        assert schema == {"$ref": "#/components/schemas/ProblemDetail"}, where


def test_no_framework_validation_schemas_are_published(spec: dict[str, Any]) -> None:
    names = set(spec.get("components", {}).get("schemas", {}))

    assert not names & {"HTTPValidationError", "ValidationError"}
    assert "ProblemDetail" in names


def test_every_route_sets_an_explicit_snake_case_operation_id(app: FastAPI) -> None:
    routes = [r.original_route for r in iter_route_contexts(app.routes) if isinstance(r.original_route, APIRoute)]

    assert routes
    for route in routes:
        assert route.operation_id is not None, route.path
        assert re.fullmatch(r"[a-z]+(_[a-z0-9]+)*", route.operation_id), route.operation_id


def test_operation_ids_are_unique(spec: dict[str, Any]) -> None:
    ids = [operation["operationId"] for _, _, operation in operations(spec)]

    assert len(ids) == len(set(ids))


def test_every_route_with_input_documents_a_422(spec: dict[str, Any]) -> None:
    for method, path, operation in operations(spec):
        if operation.get("parameters") or operation.get("requestBody"):
            assert "422" in operation["responses"], f"{method} {path}"


def test_every_route_with_a_body_documents_the_400_for_unreadable_bytes(
    spec: dict[str, Any],
) -> None:
    for method, path, operation in operations(spec):
        if operation.get("requestBody"):
            assert "400" in operation["responses"], f"{method} {path}"


def test_every_registered_problem_type_is_documented_in_some_response(app: FastAPI, spec: dict[str, Any]) -> None:
    descriptions = " ".join(response["description"] for _, response in error_responses(spec))

    takes_input = any(op.get("parameters") or op.get("requestBody") for _, _, op in operations(spec))
    expected = [
        kind
        for kind in app.state.problem_types
        if takes_input or kind != VALIDATION_ERROR  # only routes with input can answer 422
    ]
    assert expected
    for kind in expected:
        assert f"`{kind.slug}`" in descriptions, kind.slug


def test_every_operation_has_a_summary_and_tag(spec: dict[str, Any]) -> None:
    for method, path, operation in operations(spec):
        assert operation.get("summary"), f"{method} {path}"
        assert operation.get("tags"), f"{method} {path}"
        assert "Args:" not in operation.get("description", ""), f"{method} {path}"
        assert "Returns:" not in operation.get("description", ""), f"{method} {path}"


def test_metadata_describes_the_api(spec: dict[str, Any]) -> None:
    info = spec["info"]

    assert info["license"]["name"] == "Proprietary (all rights reserved)"
    assert info["contact"]["name"]
    assert info["description"]
    assert spec["servers"] == [{"url": "/", "description": "The host that serves this document"}]
    assert {tag["name"] for tag in spec["tags"]} >= {"health"}


def test_openapi_document_is_generated_once(app: FastAPI) -> None:
    assert app.openapi() is app.openapi()


def test_docs_are_off_by_default_and_on_when_enabled() -> None:
    off = TestClient(create_app(make_settings()))
    on = TestClient(create_app(make_settings(docs_enabled=True)))

    for path in ("/docs", "/redoc", "/openapi.json"):
        assert off.get(path).status_code == 404
        assert on.get(path).status_code == 200


def test_docs_off_hides_every_documentation_path_with_a_problem_404() -> None:
    client = TestClient(create_app(make_settings()))

    for path in ("/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"):
        response = client.get(path)
        assert response.status_code == 404, path
        assert response.headers["content-type"] == PROBLEM_MEDIA_TYPE, path


def test_docs_on_serve_html_pages_and_the_committed_document() -> None:
    client = TestClient(create_app(make_settings(docs_enabled=True)))
    committed = json.loads((Path(__file__).resolve().parent.parent / "openapi.json").read_text())

    assert client.get("/docs").headers["content-type"].startswith("text/html")
    assert client.get("/redoc").headers["content-type"].startswith("text/html")
    assert client.get("/openapi.json").json() == committed


def test_docs_on_do_not_change_how_the_api_answers() -> None:
    app = add_probe_routes(create_app(make_settings(docs_enabled=True)))
    client = TestClient(app)

    response = client.get("/probe/items/not-a-number")

    assert response.status_code == 422
    assert response.headers["content-type"] == PROBLEM_MEDIA_TYPE
    assert client.delete("/probe/thing").headers["Allow"] == "GET, PUT"


def test_add_tags_appends_to_the_tags_the_app_already_has() -> None:
    app = FastAPI(openapi_tags=[{"name": "first", "description": "One."}])

    add_tags(app, {"name": "second", "description": "Two."})

    assert [tag["name"] for tag in app.openapi_tags or []] == ["first", "second"]


def test_add_tags_works_on_an_app_without_tags() -> None:
    app = FastAPI()

    add_tags(app, {"name": "only", "description": "Alone."})

    assert app.openapi_tags == [{"name": "only", "description": "Alone."}]


def test_concurrent_first_calls_build_the_document_once() -> None:
    """A cold app is asked for its document by every request, from several worker threads at once."""
    app = FastAPI()
    builds: list[int] = []

    def slow_build() -> dict[str, Any]:
        builds.append(1)
        time.sleep(0.05)  # long enough for every thread to be inside, if nothing held them back
        app.openapi_schema = {"openapi": "3.1.0", "paths": {}}
        return app.openapi_schema

    app.openapi = slow_build  # type: ignore[method-assign]  # stand in for FastAPI's own build
    install_openapi(app)
    barrier = threading.Barrier(6, timeout=5)

    def ask(_: int) -> dict[str, Any]:
        barrier.wait()
        return app.openapi()

    with ThreadPoolExecutor(6) as pool:
        documents = list(pool.map(ask, range(6)))

    assert len(builds) == 1
    assert all(document is documents[0] for document in documents)
