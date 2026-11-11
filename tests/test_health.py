import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient
from hypothesis import example, given
from hypothesis import strategies as st

from formlens.main import create_app
from tests.conftest import make_settings
from tests.fakes import FakeParser


def test_health_returns_ok() -> None:
    client = TestClient(create_app())

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


# --- Stage 0 contract tests: the two probes against the committed OpenAPI document ---

PROBLEM = "application/problem+json"
HEALTH_PATHS = ["/health", "/health/ready"]


@pytest.mark.parametrize("path", HEALTH_PATHS)
def test_a_probe_answers_200_json_with_a_request_id(client: TestClient, path: str) -> None:
    response = client.get(path)

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert re.fullmatch(r"[A-Za-z0-9._-]{1,64}", response.headers["X-Request-ID"])


@pytest.mark.parametrize("path", HEALTH_PATHS)
@pytest.mark.parametrize(
    "query",
    ["verbose=1", "x=1&x=2", "x=%ff", "=", "&&&", "x[]=1", "limit=abc&limit=2"],
    ids=["unknown", "repeated", "invalid-utf8", "bare-equals", "ampersands", "brackets", "repeated-invalid"],
)
def test_a_query_string_the_spec_does_not_declare_is_ignored(client: TestClient, path: str, query: str) -> None:
    """The probes declare no query parameters, so none can make them fail or change the answer."""
    assert client.get(f"{path}?{query}").json() == client.get(path).json()
    assert client.get(f"{path}?{query}").status_code == 200


@pytest.mark.parametrize("path", HEALTH_PATHS)
@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
@pytest.mark.parametrize(
    "body",
    [b"", b"{}", b"not json", b"\xff\xfe\x00"],
    ids=["empty", "object", "not-json", "invalid-utf8"],
)
def test_a_write_to_a_probe_is_a_405_whatever_the_body_is(
    client: TestClient, path: str, method: str, body: bytes
) -> None:
    """The method is refused before any body is read: never a 400 or 422 for the body."""
    response = client.request(method, path, content=body, headers={"Content-Type": "application/json"})

    assert response.status_code == 405
    assert response.headers["Allow"] == "GET"
    assert response.headers["content-type"] == PROBLEM
    assert response.json()["title"] == "Method Not Allowed"
    assert response.json()["type"] == "about:blank"


@pytest.mark.parametrize(
    "url",
    [
        "/health/",
        "/health/ready/",
        "/Health",
        "/HEALTH/READY",
        "//health",
        "/health//ready",
        "/health/ready//",
        "/health%2fready/",
        "/health/./ready/",
        "/health%00",
        "/health%ff",
        "/health.json",
        "/health/ready.",
        "/health;a=b",
        "/health/%20",
    ],
)
def test_a_near_miss_of_a_probe_path_is_a_404_problem_and_never_a_redirect_or_a_500(
    client: TestClient, url: str
) -> None:
    response = client.get("http://testserver" + url, follow_redirects=False)

    assert response.status_code == 404
    assert "location" not in response.headers
    assert response.headers["content-type"] == PROBLEM
    assert response.json()["type"] == "about:blank"
    assert response.json()["request_id"] == response.headers["X-Request-ID"]


def test_no_path_makes_the_service_answer_with_anything_but_a_documented_status(db_url: str) -> None:
    """The app is built once, on a migrated database, and every example reads from it.

    The routes of the service are real paths a generator reaches by chance, so each is an explicit example: they must
    answer 200, 404 or 405, never a 500, and the result must not depend on what the generator happens to find.
    """
    app = create_app(make_settings(db_url=db_url), parser_factory=lambda _: FakeParser())
    app.state.parser = FakeParser()  # a loaded model: `health/ready` is a real path and must answer 200, not 503
    client = TestClient(app, raise_server_exceptions=False)
    template_id = "0192f5e0-5a3b-7c11-9d2e-3f6a1b2c4d5e"

    @example(path="v1/documents/parse")  # a real path, reached with the wrong method: 405
    @example(path="health/ready")
    @example(path="health")
    @example(path="v1/templates")
    @example(path=f"v1/templates/{template_id}")
    @example(path="v1/extractions")
    @example(path=f"v1/extractions/{template_id}")
    @given(path=st.text(alphabet=st.characters(codec="utf-8"), min_size=1, max_size=40))
    def check(path: str) -> None:
        response = client.get("/" + quote(path.lstrip("/"), safe="/"), follow_redirects=False)

        assert response.status_code in {200, 404, 405}
        assert response.status_code == 200 or response.headers["content-type"] == PROBLEM

    try:
        check()
    finally:
        app.state.database.dispose()


def test_a_request_id_is_echoed_if_and_only_if_it_is_safe(db_url: str) -> None:
    app = create_app(make_settings(db_url=db_url))  # once for all examples; the engine is released at the end
    client = TestClient(app)

    @given(request_id=st.text(alphabet=st.characters(min_codepoint=0x20, max_codepoint=0x7E), max_size=100))
    def check(request_id: str) -> None:
        safe = re.fullmatch(r"[A-Za-z0-9._-]{1,64}", request_id) is not None

        response = client.get("/health", headers={"X-Request-ID": request_id})

        echoed = response.headers["X-Request-ID"] == request_id
        assert echoed == safe
        assert re.fullmatch(r"[A-Za-z0-9._-]{1,64}", response.headers["X-Request-ID"])

    try:
        check()
    finally:
        app.state.database.dispose()


def test_the_committed_document_has_the_two_probe_operations_and_those_of_the_features() -> None:
    spec: dict[str, Any] = json.loads((Path(__file__).resolve().parent.parent / "openapi.json").read_text())

    assert {(path, method) for path, item in spec["paths"].items() for method in item} == {
        ("/health", "get"),
        ("/health/ready", "get"),
        ("/v1/documents/parse", "post"),
        ("/v1/extractions", "post"),
        ("/v1/extractions/{extraction_id}", "get"),
        ("/v1/templates", "get"),
        ("/v1/templates", "post"),
        ("/v1/templates/{template_id}", "delete"),
        ("/v1/templates/{template_id}", "get"),
        ("/v1/templates/{template_id}", "put"),
    }
    assert sorted(spec["paths"]["/health/ready"]["get"]["responses"]) == ["200", "503"]
    assert sorted(spec["paths"]["/health"]["get"]["responses"]) == ["200"]
