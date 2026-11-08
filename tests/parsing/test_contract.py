"""Every answer of POST /v1/documents/parse against the committed `openapi.json`, not against the code."""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any, Final

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx2 import Response
from jsonschema import Draft202012Validator

from formlens.config import Settings
from formlens.parsing.exceptions import InvalidFile, ParseFailed
from tests.conftest import make_settings
from tests.documents import MULTIPART, multipart_body, png_of_size, sample
from tests.fakes import FakeParser

URL = "/v1/documents/parse"
TYPE = "urn:problem:formlens:"
SPEC: Final[dict[str, Any]] = json.loads((Path(__file__).resolve().parents[2] / "openapi.json").read_text())
OPERATION: Final[dict[str, Any]] = SPEC["paths"][URL]["post"]

type Scenario = Callable[[FastAPI, TestClient], Response]


@pytest.fixture
def settings() -> Settings:
    return make_settings(max_upload_mb=1)


def post(client: TestClient, content: bytes, *, params: dict[str, str] | None = None) -> Response:
    return client.post(URL, files={"file": ("scan.png", content, "image/png")}, params=params)


def markdown(app: FastAPI, client: TestClient) -> Response:
    return post(client, sample("sample.png"))


def plain_text(app: FastAPI, client: TestClient) -> Response:
    return post(client, sample("sample.png"), params={"format": "text"})


def empty_file(app: FastAPI, client: TestClient) -> Response:
    return post(client, b"")


def unreadable_file(app: FastAPI, client: TestClient) -> Response:
    app.state.parser = FakeParser(error=InvalidFile())
    return post(client, sample("sample.png"))


def malformed_multipart(app: FastAPI, client: TestClient) -> Response:
    headers = {"Content-Type": MULTIPART.replace("formlens-test-boundary", "another-boundary")}
    return client.post(URL, content=multipart_body(sample("sample.png")), headers=headers)


def too_large_for_the_service(app: FastAPI, client: TestClient) -> Response:
    return post(client, png_of_size(1024 * 1024 + 1))


def too_large_for_the_body_cap(app: FastAPI, client: TestClient) -> Response:
    return post(client, png_of_size(3 * 1024 * 1024))


def not_a_document(app: FastAPI, client: TestClient) -> Response:
    return post(client, b"just text")


def unknown_format(app: FastAPI, client: TestClient) -> Response:
    return post(client, sample("sample.png"), params={"format": "html"})


def no_file(app: FastAPI, client: TestClient) -> Response:
    return client.post(URL, data={"other": "value"}, files={"x": ("x", b"y")})


def parse_failed(app: FastAPI, client: TestClient) -> Response:
    app.state.parser = FakeParser(error=ParseFailed())
    return post(client, sample("sample.png"))


def parser_busy(app: FastAPI, client: TestClient) -> Response:
    with app.state.parse_slots.hold():
        return post(client, sample("sample.png"))


def model_unavailable(app: FastAPI, client: TestClient) -> Response:
    app.state.parser = None
    return post(client, sample("sample.png"))


SCENARIOS = [
    pytest.param(markdown, 200, None, id="200-markdown"),
    pytest.param(plain_text, 200, None, id="200-text"),
    pytest.param(empty_file, 400, "invalid-file", id="400-empty-file"),
    pytest.param(unreadable_file, 400, "invalid-file", id="400-unreadable-file"),
    pytest.param(malformed_multipart, 400, "about:blank", id="400-malformed-multipart"),
    pytest.param(too_large_for_the_service, 413, "file-too-large", id="413-checked-by-the-service"),
    pytest.param(too_large_for_the_body_cap, 413, "file-too-large", id="413-refused-by-the-body-cap"),
    pytest.param(not_a_document, 415, "unsupported-media-type", id="415"),
    pytest.param(unknown_format, 422, "validation-error", id="422-unknown-format"),
    pytest.param(no_file, 422, "validation-error", id="422-no-file"),
    pytest.param(parse_failed, 500, "parse-failed", id="500"),
    pytest.param(parser_busy, 503, "parser-busy", id="503-parser-busy"),
    pytest.param(model_unavailable, 503, "model-unavailable", id="503-model-unavailable"),
]


def problem_type(slug: str) -> str:
    return slug if slug == "about:blank" else f"{TYPE}{slug}"


def validator_for(schema: dict[str, Any]) -> Draft202012Validator:
    """Validate against a schema of the document, with its `$ref`s resolved inside the same document."""
    return Draft202012Validator({**schema, "components": SPEC["components"]})


@pytest.mark.parametrize(("scenario", "status", "slug"), SCENARIOS)
def test_the_answer_is_a_documented_status_with_a_documented_media_type_and_a_valid_body(
    app: FastAPI, client: TestClient, scenario: Scenario, status: int, slug: str | None
) -> None:
    response = scenario(app, client)

    documented = OPERATION["responses"][str(status)]
    media_type = response.headers["content-type"].split(";")[0]
    assert response.status_code == status
    assert list(documented["content"]) == [media_type]
    validator_for(documented["content"][media_type]["schema"]).validate(response.json())
    if slug is not None:
        assert response.json()["type"] == problem_type(slug)
        assert response.json()["status"] == status


def test_every_status_the_spec_documents_has_a_scenario_and_every_scenario_a_documented_status() -> None:
    exercised = {str(p.values[1]) for p in SCENARIOS}

    assert exercised == set(OPERATION["responses"])


def test_the_success_body_has_exactly_the_documented_properties(app: FastAPI, client: TestClient) -> None:
    schema = SPEC["components"]["schemas"]["ParseResponse"]

    body = markdown(app, client).json()

    assert set(body) == set(schema["properties"])
    assert set(schema["required"]) == set(schema["properties"])


@pytest.mark.parametrize(("scenario", "status", "slug"), SCENARIOS)
def test_a_supplied_request_id_comes_back_in_the_header_and_in_every_error_body(
    app: FastAPI, client: TestClient, scenario: Scenario, status: int, slug: str | None
) -> None:
    client.headers["X-Request-ID"] = "client-id-4711"

    response = scenario(app, client)

    assert response.status_code == status
    assert response.headers["X-Request-ID"] == "client-id-4711"
    if status >= 400:
        assert response.json()["request_id"] == "client-id-4711"


@pytest.mark.parametrize(("scenario", "status", "slug"), SCENARIOS)
def test_retry_after_is_sent_with_a_busy_parser_only_and_it_is_a_whole_number_of_seconds(
    app: FastAPI, client: TestClient, scenario: Scenario, status: int, slug: str | None
) -> None:
    response = scenario(app, client)

    documented = OPERATION["responses"]["503"]["headers"]["Retry-After"]["schema"]
    assert documented["type"] == "integer"
    assert ("Retry-After" in response.headers) == (slug == "parser-busy")
    if slug == "parser-busy":
        assert response.headers["Retry-After"].isdigit()
