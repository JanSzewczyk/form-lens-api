"""The HTTP contract of the core, proved without any domain module.

Every case uses `/health`, `/health/ready` and the probe routes of `tests/probes.py`, so this file
passes unchanged when the example domain is removed. A case that needs a domain module's routes
belongs with that module's tests.

Rules checked here: every error is Problem Details with its own type, title and status; every
response carries `X-Request-ID`; a wrong method is a 405 with `Allow`; a trailing slash is a 404;
CORS and validation never leak what the client sent; a 500 carries the request id and the CORS
headers.
"""

import re
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx2 import Response

from formlens.health.readiness import register_readiness_check
from formlens.main import create_app
from tests.conftest import make_settings
from tests.probes import add_probe_routes

PROBLEM = "application/problem+json"
TYPE = "urn:problem:formlens:"
JSON_BYTES = {"Content-Type": "application/json"}
REQUEST_ID_SHAPE = re.compile(r"[A-Za-z0-9._-]{1,64}")
PROBLEM_FIELDS = {"type", "title", "status", "detail", "errors", "request_id"}
SECRET = "s3cr3t-hunter2"
HTTP_METHODS = ("GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD")
ORIGIN = "https://app.example.com"

type Sender = Callable[[TestClient, FastAPI], Response]


def concrete(path: str) -> str:
    """Fill each path parameter with a value that matches the route."""
    return re.sub(r"\{[^}]+\}", "7", path)


def send_unreadable_body(client: TestClient, app: FastAPI) -> Response:
    return client.post("/probe/body", content=b"\xff\xfe\x00", headers=JSON_BYTES)


def send_unknown_path(client: TestClient, app: FastAPI) -> Response:
    return client.get("/no/such/path")


def send_wrong_method(client: TestClient, app: FastAPI) -> Response:
    return client.delete("/probe/thing")


def send_domain_refusal(client: TestClient, app: FastAPI) -> Response:
    return client.get("/probe/refused")


def send_invalid_query(client: TestClient, app: FastAPI) -> Response:
    return client.get("/probe/limit", params={"limit": 1000})


def send_invalid_path_value(client: TestClient, app: FastAPI) -> Response:
    return client.get("/probe/items/not-a-number")


def send_invalid_body(client: TestClient, app: FastAPI) -> Response:
    return client.post("/probe/body", json={"name": "x" * 11})


def send_when_not_ready(client: TestClient, app: FastAPI) -> Response:
    def broken() -> None:
        raise ConnectionError("db password is hunter2")

    register_readiness_check(app, "database", broken)
    return client.get("/health/ready")


def send_when_the_server_fails(client: TestClient, app: FastAPI) -> Response:
    return client.get("/probe/boom")


ERROR_CASES = [
    pytest.param(send_unreadable_body, 400, "about:blank", "Bad Request", id="400-unreadable-body"),
    pytest.param(send_unknown_path, 404, "about:blank", "Not Found", id="404-unknown-path"),
    pytest.param(send_wrong_method, 405, "about:blank", "Method Not Allowed", id="405-wrong-method"),
    pytest.param(
        send_domain_refusal,
        409,
        f"{TYPE}probe-refused",
        "Probe refused",
        id="409-domain-refusal",
    ),
    pytest.param(
        send_invalid_query,
        422,
        f"{TYPE}validation-error",
        "Request validation failed",
        id="422-invalid-query",
    ),
    pytest.param(
        send_invalid_path_value,
        422,
        f"{TYPE}validation-error",
        "Request validation failed",
        id="422-invalid-path",
    ),
    pytest.param(
        send_invalid_body,
        422,
        f"{TYPE}validation-error",
        "Request validation failed",
        id="422-invalid-body",
    ),
    pytest.param(
        send_when_not_ready,
        503,
        f"{TYPE}service-not-ready",
        "Service not ready",
        id="503-service-not-ready",
    ),
    pytest.param(
        send_when_the_server_fails,
        500,
        "about:blank",
        "Internal Server Error",
        id="500-unhandled-exception",
    ),
]


@pytest.mark.parametrize(("send", "status", "type_", "title"), ERROR_CASES)
def test_every_error_is_problem_details_with_its_own_type_title_and_status(
    send: Sender, status: int, type_: str, title: str, probe_app: FastAPI, probe: TestClient
) -> None:
    response = send(probe, probe_app)

    body = response.json()
    assert response.status_code == status
    assert response.headers["content-type"] == PROBLEM
    assert (body["type"], body["title"], body["status"]) == (type_, title, status)
    assert isinstance(body["detail"], str)
    assert set(body) <= PROBLEM_FIELDS
    assert ("errors" in body) == (status == 422)


@pytest.mark.parametrize(("send", "status", "type_", "title"), ERROR_CASES)
def test_every_error_carries_the_request_id_in_the_header_and_the_body(
    send: Sender, status: int, type_: str, title: str, probe_app: FastAPI, probe: TestClient
) -> None:
    response = send(probe, probe_app)

    header = response.headers.get("X-Request-ID")
    assert header is not None, f"{status} has no X-Request-ID header"
    assert REQUEST_ID_SHAPE.fullmatch(header)
    assert response.json()["request_id"] == header


@pytest.mark.parametrize(("send", "status", "type_", "title"), ERROR_CASES)
def test_a_supplied_request_id_is_echoed_by_every_error(
    send: Sender, status: int, type_: str, title: str, probe_app: FastAPI
) -> None:
    with TestClient(probe_app, raise_server_exceptions=False, headers={"X-Request-ID": "client-id-7"}) as client:
        response = send(client, probe_app)

    assert response.headers.get("X-Request-ID") == "client-id-7"
    assert response.json()["request_id"] == "client-id-7"


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/health", 200),
        ("/health/ready", 200),
        ("/probe/thing", 200),
        ("/probe/items/7", 200),
    ],
    ids=["health", "ready", "probe", "probe-with-path-value"],
)
def test_successful_responses_carry_a_request_id_too(probe: TestClient, path: str, expected: int) -> None:
    response = probe.get(path)

    assert response.status_code == expected
    assert REQUEST_ID_SHAPE.fullmatch(response.headers["X-Request-ID"])


def test_a_request_id_of_exactly_64_characters_is_echoed(client: TestClient) -> None:
    response = client.get("/health", headers={"X-Request-ID": "a" * 64})

    assert response.headers["X-Request-ID"] == "a" * 64


@pytest.mark.parametrize(
    "inbound",
    [b"", b"id\twith\ttab", b"\xfc\xf1", b"a/b", b"a" * 65],
    ids=["empty", "tab", "non-ascii", "slash", "too-long"],
)
def test_an_unsafe_request_id_is_replaced_on_an_error_too(client: TestClient, inbound: bytes) -> None:
    response = client.get("/no/such/path", headers={b"X-Request-ID": inbound})

    header = response.headers["X-Request-ID"]
    assert header.encode() != inbound
    assert REQUEST_ID_SHAPE.fullmatch(header)
    assert response.json()["request_id"] == header


def test_a_wrong_method_lists_every_method_of_a_path_that_has_two_routes(
    probe: TestClient,
) -> None:
    """Starlette alone reports the methods of the first matching route (`GET`)."""
    response = probe.delete("/probe/thing")

    assert response.status_code == 405
    assert response.headers["Allow"] == "GET, PUT"


def test_every_documented_path_answers_a_method_it_lacks_with_a_405_listing_its_methods(
    probe_app: FastAPI, probe: TestClient
) -> None:
    """Walks the spec of whatever the app serves, probes included; nothing here names a module."""
    paths = probe_app.openapi()["paths"]
    assert {"/health", "/health/ready", "/probe/thing"} <= set(paths)

    for path, item in paths.items():
        documented = sorted(method.upper() for method in item)
        for method in HTTP_METHODS:
            if method in documented:
                continue
            response = probe.request(method, concrete(path))

            where = f"{method} {path}"
            allow = sorted(m.strip() for m in response.headers["Allow"].split(","))
            assert response.status_code == 405, where
            assert allow == documented, where
            if method != "HEAD":  # a HEAD answer has no body by definition
                assert response.headers["content-type"] == PROBLEM, where
                assert response.json()["title"] == "Method Not Allowed", where


def test_every_documented_path_answers_a_trailing_slash_with_a_404_problem_not_a_redirect(
    probe_app: FastAPI, probe: TestClient
) -> None:
    paths = probe_app.openapi()["paths"]

    for path, item in paths.items():
        method = next(iter(item)).upper()
        response = probe.request(method, concrete(path) + "/", follow_redirects=False)

        assert response.status_code == 404, path
        assert "location" not in response.headers, path
        assert response.headers["content-type"] == PROBLEM, path


@pytest.mark.parametrize("path", ["/", "/probe", "/probe/thing/extra", "/health/live", "/v2/x"])
def test_an_unknown_path_is_a_404_problem(client: TestClient, path: str) -> None:
    response = client.get(path)

    assert response.status_code == 404
    assert response.headers["content-type"] == PROBLEM


def test_a_route_outside_the_spec_still_answers_a_wrong_method_with_its_own_allow(
    app: FastAPI, client: TestClient
) -> None:
    @app.get("/internal/ping", include_in_schema=False)
    def ping() -> dict[str, str]:
        return {}

    response = client.post("/internal/ping")

    assert response.status_code == 405
    assert response.headers["Allow"] == "GET"
    assert response.headers["content-type"] == PROBLEM


def test_a_validation_error_never_echoes_what_the_client_sent(probe: TestClient) -> None:
    payloads = [
        {"name": SECRET},
        {"name": "ok", "password": SECRET},
        {"name": "y" * 11, "password": SECRET},
    ]

    for payload in payloads:
        response = probe.post("/probe/body", json=payload)

        assert response.status_code == 422
        assert SECRET not in response.text
        assert "y" * 11 not in response.text
        for issue in response.json()["errors"]:
            assert set(issue) == {"loc", "msg", "type"}
            assert issue["loc"][0] == "body"


def test_a_validation_error_in_the_path_or_query_never_echoes_the_value(
    probe: TestClient,
) -> None:
    for response in (
        probe.get(f"/probe/items/{SECRET}"),
        probe.get("/probe/limit", params={"limit": SECRET}),
        probe.get("/probe/limit", params={"limit": SECRET, "offset": SECRET}),
    ):
        assert response.status_code == 422
        assert SECRET not in response.text


def test_a_path_validation_error_names_the_parameter(probe: TestClient) -> None:
    errors = probe.get("/probe/items/not-a-number").json()["errors"]

    assert errors[0]["loc"] == ["path", "item_id"]


def test_the_health_payloads_are_exactly_the_documented_ones(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/health/ready").json() == {"status": "ready", "checks": {}}


def test_a_failed_readiness_check_does_not_leak_into_other_routes(probe_app: FastAPI, probe: TestClient) -> None:
    def broken() -> None:
        raise ConnectionError("db password is hunter2")

    register_readiness_check(probe_app, "database", broken)

    assert probe.get("/health/ready").status_code == 503
    assert probe.get("/health").status_code == 200
    assert probe.get("/probe/thing").status_code == 200


def test_readiness_names_every_failed_check_sorted_and_the_passing_ones_are_not_listed(
    app: FastAPI, client: TestClient
) -> None:
    def broken() -> None:
        raise ConnectionError("hunter2")

    register_readiness_check(app, "queue", broken)
    register_readiness_check(app, "cache", lambda: None)
    register_readiness_check(app, "database", broken)

    body = client.get("/health/ready").json()

    assert body["detail"] == "Not ready: database, queue"
    assert "hunter2" not in str(body)


class TestUnhandledError:
    """The 500 is answered by `UnhandledErrorMiddleware`, inside request context and CORS."""

    def test_it_is_the_generic_problem_without_the_exception_text(self, probe: TestClient) -> None:
        response = probe.get("/probe/boom")

        assert response.status_code == 500
        assert response.json()["detail"] == "The server failed to process the request."
        assert "internal detail" not in response.text

    def test_the_header_and_the_body_name_the_same_request_id(self, probe: TestClient) -> None:
        response = probe.get("/probe/boom")

        assert response.headers["X-Request-ID"] == response.json()["request_id"]


class TestCors:
    @pytest.fixture
    def cors_app(self) -> FastAPI:
        return add_probe_routes(create_app(make_settings(cors_origins=[ORIGIN])))

    @pytest.fixture
    def cors(self, cors_app: FastAPI) -> Iterator[TestClient]:
        with TestClient(cors_app, raise_server_exceptions=False) as test_client:
            yield test_client

    @pytest.mark.parametrize(
        ("path", "status"),
        [("/no/such/path", 404), ("/probe/limit?limit=1000", 422), ("/probe/boom", 500)],
        ids=["404", "422", "500"],
    )
    def test_error_responses_carry_the_cors_headers(self, cors: TestClient, path: str, status: int) -> None:
        response = cors.get(path, headers={"Origin": ORIGIN})

        assert response.status_code == status
        assert response.headers["access-control-allow-origin"] == ORIGIN
        assert "X-Request-ID" in response.headers["access-control-expose-headers"]
        assert response.headers["content-type"] == PROBLEM

    def test_a_500_carries_the_cors_headers_and_the_request_id_together(self, cors: TestClient) -> None:
        response = cors.get("/probe/boom", headers={"Origin": ORIGIN})

        assert response.headers["access-control-allow-origin"] == ORIGIN
        assert response.headers["X-Request-ID"] == response.json()["request_id"]

    def test_an_origin_outside_the_list_gets_no_cors_headers(self, cors: TestClient) -> None:
        response = cors.get("/health", headers={"Origin": "https://evil.example.com"})

        assert response.status_code == 200
        assert "access-control-allow-origin" not in response.headers

    def test_a_preflight_allows_only_the_declared_methods_and_no_credentials(self, cors: TestClient) -> None:
        response = cors.options(
            "/probe/thing",
            headers={
                "Origin": ORIGIN,
                "Access-Control-Request-Method": "PUT",
                "Access-Control-Request-Headers": "content-type",
            },
        )

        allowed = {m.strip() for m in response.headers["access-control-allow-methods"].split(",")}
        assert response.status_code == 200
        assert "PATCH" not in allowed
        assert {"GET", "POST", "PUT"} <= allowed
        assert "access-control-allow-credentials" not in response.headers
        assert response.headers["access-control-allow-origin"] == ORIGIN

    REFUSALS = pytest.mark.parametrize(
        "headers",
        [
            {"Access-Control-Request-Method": "PATCH"},
            {"Origin": "https://evil.example.com", "Access-Control-Request-Method": "POST"},
            {"Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "x-evil"},
        ],
        ids=["method", "origin", "header"],
    )

    @REFUSALS
    def test_a_refused_preflight_is_a_400(self, cors: TestClient, headers: dict[str, str]) -> None:
        response = cors.options("/probe/thing", headers={"Origin": ORIGIN, **headers})

        assert response.status_code == 400

    @REFUSALS
    def test_a_refused_preflight_is_a_problem_not_plain_text(self, cors: TestClient, headers: dict[str, str]) -> None:
        """`info.description` promises that every error is Problem Details."""
        response = cors.options("/probe/thing", headers={"Origin": ORIGIN, **headers})

        body: dict[str, Any] = response.json()
        assert response.headers["content-type"] == PROBLEM
        assert body["status"] == 400
        assert body["request_id"] == response.headers["X-Request-ID"]

    def test_without_cors_a_preflight_is_a_405_problem(self, probe: TestClient) -> None:
        response = probe.options(
            "/probe/thing",
            headers={"Origin": ORIGIN, "Access-Control-Request-Method": "PUT"},
        )

        assert response.status_code == 405
        assert response.headers["content-type"] == PROBLEM
