"""The OpenAPI links of the example domain point at real operations and real fields.

Schemathesis follows these links to reach the operations that need an id (a loan to fetch or
return), so a link that names a missing operation or field would hide them again.
"""

from typing import Any

import pytest
from fastapi import FastAPI

PREFIX = "#/components/schemas/"


def operations(spec: dict[str, Any]) -> dict[str, tuple[str, dict[str, Any]]]:
    """Map every operation id to its path and operation object."""
    return {
        operation["operationId"]: (path, operation)
        for path, methods in spec["paths"].items()
        for operation in methods.values()
    }


def linked_responses(spec: dict[str, Any]) -> list[tuple[str, str, dict[str, Any], dict[str, Any]]]:
    """List (operation id, link name, link, response object) for every link in the document."""
    return [
        (operation["operationId"], name, link, response)
        for methods in spec["paths"].values()
        for operation in methods.values()
        for response in operation["responses"].values()
        for name, link in response.get("links", {}).items()
    ]


def schema_of(spec: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
    """Resolve a `$ref` to a component schema."""
    ref = schema.get("$ref")
    return spec["components"]["schemas"][ref.removeprefix(PREFIX)] if ref else schema


@pytest.fixture
def spec(app: FastAPI) -> dict[str, Any]:
    document: dict[str, Any] = app.openapi()
    return document


def test_the_example_declares_links(spec: dict[str, Any]) -> None:
    sources = {operation_id for operation_id, _, _, _ in linked_responses(spec)}

    assert sources == {"create_book", "create_loan"}


def test_every_link_names_an_existing_operation(spec: dict[str, Any]) -> None:
    known = operations(spec)

    for operation_id, name, link, _ in linked_responses(spec):
        assert link["operationId"] in known, f"{operation_id}: link {name}"


def test_every_link_parameter_is_a_path_parameter_of_its_target(spec: dict[str, Any]) -> None:
    known = operations(spec)

    for operation_id, name, link, _ in linked_responses(spec):
        _, target = known[link["operationId"]]
        path_parameters = {p["name"] for p in target.get("parameters", []) if p["in"] == "path"}
        assert set(link.get("parameters", {})) <= path_parameters, f"{operation_id}: link {name}"


def test_every_linked_field_exists_in_the_response_that_carries_the_link(
    spec: dict[str, Any],
) -> None:
    for operation_id, name, link, response in linked_responses(spec):
        body = schema_of(spec, response["content"]["application/json"]["schema"])
        expressions = [*link.get("parameters", {}).values(), *link.get("requestBody", {}).values()]
        for expression in expressions:
            if expression.startswith("$response.body#/"):
                field = expression.removeprefix("$response.body#/")
                assert field in body["properties"], f"{operation_id}: link {name} reads {field}"


def test_every_link_request_body_field_exists_in_the_target_request(spec: dict[str, Any]) -> None:
    known = operations(spec)

    for operation_id, name, link, _ in linked_responses(spec):
        if "requestBody" not in link:
            continue
        _, target = known[link["operationId"]]
        request = target["requestBody"]["content"]["application/json"]["schema"]
        assert set(link["requestBody"]) <= set(schema_of(spec, request)["properties"]), f"{operation_id}: link {name}"
