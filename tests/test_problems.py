import asyncio
import json
from typing import Any

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from formlens.main import create_app
from formlens.middleware import UnhandledErrorMiddleware
from formlens.problems import (
    PROBLEM_MEDIA_TYPE,
    ProblemType,
    malformed_body_response,
    problem_response,
    register_domain_errors,
)
from tests.conftest import make_settings
from tests.probes import REFUSED, Refused

PROBLEM_JSON = PROBLEM_MEDIA_TYPE
JSON = {"Content-Type": "application/json"}


def body_of(response: Any) -> dict[str, Any]:
    assert response.headers["content-type"] == PROBLEM_JSON
    return dict(response.json())


def test_unknown_path_is_a_404_problem_with_the_request_id(probe: TestClient) -> None:
    response = probe.get("/probe/missing")

    body = body_of(response)
    assert response.status_code == 404
    assert (body["type"], body["title"], body["status"]) == ("about:blank", "Not Found", 404)
    assert body["request_id"] == response.headers["X-Request-ID"]


def test_trailing_slash_is_a_404_not_a_redirect(probe: TestClient) -> None:
    response = probe.get("/health/", follow_redirects=False)

    assert response.status_code == 404
    body_of(response)


def test_405_lists_every_method_of_the_path(probe: TestClient) -> None:
    response = probe.delete("/probe/thing")

    assert response.status_code == 405
    assert response.headers["Allow"] == "GET, PUT"
    assert body_of(response)["title"] == "Method Not Allowed"


def test_http_exception_keeps_its_headers(probe: TestClient) -> None:
    response = probe.get("/probe/auth")

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert body_of(response)["detail"] == "Bearer token required"


@pytest.fixture
def raising() -> TestClient:
    """A client for an app with one route that raises the `HTTPException` the query describes."""
    app = create_app(make_settings())

    @app.get("/raise", operation_id="get_raise")
    def raise_it(status: int, structured: bool = False) -> None:
        raise HTTPException(status, {"code": "conflict", "id": 1} if structured else None)

    return TestClient(app, raise_server_exceptions=False)


@pytest.mark.parametrize("status", [204, 205, 304])
def test_an_http_exception_with_a_status_that_forbids_content_has_no_body(raising: TestClient, status: int) -> None:
    response = raising.get("/raise", params={"status": status})

    assert response.status_code == status
    assert response.content == b""
    assert "content-type" not in response.headers
    assert response.headers["X-Request-ID"]


def test_an_http_exception_with_a_status_http_does_not_know_keeps_it(raising: TestClient) -> None:
    response = raising.get("/raise", params={"status": 499})

    assert response.status_code == 499
    assert body_of(response)["title"] == "Error"


def test_an_http_exception_with_a_structured_detail_leaves_it_out(raising: TestClient) -> None:
    response = raising.get("/raise", params={"status": 409, "structured": True})

    body = body_of(response)
    assert (response.status_code, body["title"]) == (409, "Conflict")
    assert "detail" not in body


def test_validation_error_names_the_field_and_never_echoes_the_input(probe: TestClient) -> None:
    response = probe.get("/probe/limit", params={"limit": "s3cr3t-value"})

    body = body_of(response)
    assert response.status_code == 422
    assert body["type"] == "urn:problem:formlens:validation-error"
    [issue] = body["errors"]
    assert set(issue) == {"loc", "msg", "type"}
    assert issue["loc"] == ["query", "limit"]
    assert "s3cr3t-value" not in response.text


def test_malformed_json_body_is_a_422_without_the_body(probe: TestClient) -> None:
    response = probe.post(
        "/probe/body",
        content='{"name": "leaky-password"',
        headers={"Content-Type": "application/json"},
    )

    body = body_of(response)
    assert response.status_code == 422
    assert body["errors"][0]["type"] == "json_invalid"
    assert "leaky-password" not in response.text


def test_wrong_body_type_is_a_422_with_loc_msg_type_only(probe: TestClient) -> None:
    response = probe.post("/probe/body", json={"name": 5})

    [issue] = body_of(response)["errors"]
    assert issue["loc"] == ["body", "name"]
    assert set(issue) == {"loc", "msg", "type"}


def test_unhandled_exception_is_a_generic_500_problem(probe: TestClient) -> None:
    response = probe.get("/probe/boom")

    body = body_of(response)
    assert response.status_code == 500
    assert body["title"] == "Internal Server Error"
    assert "internal detail" not in response.text


def test_domain_error_gets_its_own_type_and_is_logged_as_a_warning(
    probe_app: FastAPI, capsys: pytest.CaptureFixture[str]
) -> None:
    response = TestClient(probe_app).get("/probe/refused")

    body = body_of(response)
    assert response.status_code == 409
    assert body["type"] == "urn:problem:formlens:probe-refused"
    assert body["title"] == "Probe refused"
    assert body["detail"] == "not today"
    refusals = [json.loads(line) for line in capsys.readouterr().out.splitlines() if '"request_refused"' in line]
    assert refusals
    assert refusals[0]["level"] == "warning"
    assert "exception" not in refusals[0]


def test_problem_response_documents_each_type_slug() -> None:
    entry = problem_response(REFUSED)

    assert "`probe-refused`" in entry["description"]
    assert entry["content"] == {PROBLEM_JSON: {}}


def test_an_unhandled_error_still_carries_the_cors_headers_and_the_request_id() -> None:
    origin = "https://app.example.com"
    app = create_app(make_settings(cors_origins=[origin]))

    @app.get("/probe/boom", operation_id="get_probe_boom_cors")
    def boom() -> None:
        raise RuntimeError("internal detail that must not leak")

    response = TestClient(app, raise_server_exceptions=False).get("/probe/boom", headers={"Origin": origin})

    assert response.status_code == 500
    assert response.headers["access-control-allow-origin"] == origin
    assert response.headers["X-Request-ID"] == response.json()["request_id"]


def test_an_exception_after_the_response_started_is_not_swallowed() -> None:
    async def half_a_response(scope: Scope, receive: Receive, send: Send) -> None:
        await send({"type": "http.response.start", "status": 200, "headers": []})
        raise RuntimeError("broke after the headers were sent")

    client = TestClient(UnhandledErrorMiddleware(half_a_response))

    with pytest.raises(RuntimeError, match="after the headers"):
        client.get("/")


def test_a_websocket_scope_passes_through_the_unhandled_error_middleware() -> None:
    seen: list[str] = []

    async def record(scope: Scope, receive: Receive, send: Send) -> None:
        seen.append(scope["type"])

    asyncio.run(UnhandledErrorMiddleware(record)({"type": "websocket"}, _no_receive, _no_send))

    assert seen == ["websocket"]


async def _no_receive() -> Message:
    return {"type": "websocket.disconnect"}


async def _no_send(_message: Message) -> None:
    return None


def test_json_with_an_integer_beyond_the_parser_limit_is_a_422_but_invalid_utf8_stays_400(
    probe: TestClient,
) -> None:
    long_integer = b'{"name": ' + b"9" * 5000 + b"}"

    too_long = probe.post("/probe/body", content=long_integer, headers=JSON)
    not_text = probe.post("/probe/body", content=b'{"name": "\xff"}', headers=JSON)

    assert (too_long.status_code, too_long.json()["errors"][0]["loc"]) == (422, ["body"])
    assert "9999" not in too_long.text
    assert not_text.status_code == 400


@pytest.mark.parametrize(
    "value",
    ["abc", "9" * 5000],
    ids=["not-a-number", "beyond-the-digit-limit"],
)
def test_a_400_the_application_raises_from_a_value_error_stays_a_400(probe: TestClient, value: str) -> None:
    """`int()` of a long string raises the same `ValueError` the JSON parser does."""
    response = probe.get("/probe/convert", params={"value": value})

    body = body_of(response)
    assert response.status_code == 400
    assert body["detail"] == "value must be an integer"
    assert "errors" not in body


def test_a_failure_in_the_outermost_middleware_is_still_a_500_problem() -> None:
    app = create_app(make_settings())

    class Broken:
        def __init__(self, app: ASGIApp) -> None:
            self.app = app

        async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
            raise RuntimeError("middleware failed")

    app.add_middleware(Broken)

    response = TestClient(app, raise_server_exceptions=False).get("/health")

    assert response.status_code == 500
    assert response.headers["content-type"] == PROBLEM_JSON
    assert "middleware failed" not in response.text


class Missing(Exception):
    """Probe: a parent error mapped once, raised through a subclass."""


class MissingPart(Missing):
    """Probe: has no mapping of its own."""


MISSING = ProblemType("probe-missing", "Probe missing", 404)


def test_register_domain_errors_maps_each_exception_and_its_subclasses_and_records_the_types(
    probe_app: FastAPI,
) -> None:
    @probe_app.get("/probe/missing-part", operation_id="get_probe_missing_part")
    def missing_part() -> None:
        raise MissingPart("part 7")

    register_domain_errors(probe_app, {Missing: MISSING, Refused: REFUSED})

    response = TestClient(probe_app).get("/probe/missing-part")

    body = body_of(response)
    assert response.status_code == 404
    assert (body["type"], body["detail"]) == (
        "urn:problem:formlens:probe-missing",
        "part 7",
    )
    assert MISSING in probe_app.state.problem_types
    assert REFUSED in probe_app.state.problem_types


def test_the_malformed_body_response_documents_a_problem_without_a_slug() -> None:
    entry = malformed_body_response()

    assert entry["content"] == {PROBLEM_JSON: {}}
    assert "could not be read as text" in entry["description"]


class Busy(Exception):
    """Probe: a service failure that tells the client when to try again."""

    def __init__(self, retry_after_seconds: object) -> None:
        super().__init__("busy")
        self.retry_after_seconds = retry_after_seconds


BUSY = ProblemType("probe-busy", "Probe busy", 503)
BROKEN = ProblemType("probe-broken", "Probe broken", 500)


def raise_on_get(app: FastAPI, path: str, error: Exception, mapping: dict[type[Exception], ProblemType]) -> Any:
    @app.get(path, operation_id=f"get{path.replace('/', '_')}")
    def route() -> None:
        raise error

    register_domain_errors(app, mapping)
    return TestClient(app).get(path)


def test_a_domain_error_with_retry_after_seconds_sets_the_retry_after_header(probe_app: FastAPI) -> None:
    response = raise_on_get(probe_app, "/probe/busy", Busy(7), {Busy: BUSY})

    assert response.status_code == 503
    assert response.headers["Retry-After"] == "7"
    assert body_of(response)["type"] == "urn:problem:formlens:probe-busy"


def test_a_domain_error_without_retry_after_seconds_sends_no_retry_after_header(probe_app: FastAPI) -> None:
    response = TestClient(probe_app).get("/probe/refused")

    assert response.status_code == 409
    assert "Retry-After" not in response.headers


@pytest.mark.parametrize("value", [None, True, -1, "5", 1.5], ids=["none", "bool", "negative", "text", "float"])
def test_a_retry_after_seconds_that_is_not_a_whole_count_is_ignored(probe_app: FastAPI, value: object) -> None:
    response = raise_on_get(probe_app, "/probe/busy", Busy(value), {Busy: BUSY})

    assert response.status_code == 503
    assert "Retry-After" not in response.headers


def test_a_service_failure_is_logged_as_an_error_and_a_refusal_as_a_warning(
    probe_app: FastAPI, capsys: pytest.CaptureFixture[str]
) -> None:
    response = raise_on_get(probe_app, "/probe/broken", Busy(3), {Busy: BROKEN})
    TestClient(probe_app).get("/probe/refused")

    assert response.status_code == 500
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.startswith("{")]
    levels = {
        event["event"]: event["level"] for event in events if event["event"] in {"request_failed", "request_refused"}
    }
    assert levels == {"request_failed": "error", "request_refused": "warning"}
    failed = next(event for event in events if event["event"] == "request_failed")
    assert (failed["problem"], failed["status"]) == ("probe-broken", 500)
    assert "exception" not in failed


def test_a_503_that_says_when_to_retry_is_a_warning_in_both_log_lines_and_a_503_that_does_not_is_an_error(
    probe_app: FastAPI, capsys: pytest.CaptureFixture[str]
) -> None:
    """Load shedding is expected under load; a service that is down is not."""
    shed = raise_on_get(probe_app, "/probe/shed", Busy(5), {Busy: BUSY})
    down = raise_on_get(probe_app, "/probe/down", Busy(None), {Busy: BUSY})

    events = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.startswith("{")]
    by_request = {
        (e["request_id"], e["event"]): e["level"]
        for e in events
        if e["event"] in {"request_failed", "request_refused", "request_completed"}
    }
    shed_id, down_id = shed.headers["X-Request-ID"], down.headers["X-Request-ID"]
    assert (shed.status_code, down.status_code) == (503, 503)
    assert by_request[shed_id, "request_refused"] == "warning"
    assert by_request[shed_id, "request_completed"] == "warning"
    assert (shed_id, "request_failed") not in by_request
    assert by_request[down_id, "request_failed"] == "error"
    assert by_request[down_id, "request_completed"] == "error"


def test_a_503_with_a_retry_after_header_that_no_domain_error_asked_for_stays_an_error(
    probe_app: FastAPI, capsys: pytest.CaptureFixture[str]
) -> None:
    """Only a domain error that carries `retry_after_seconds` is load shedding; a bare header is not."""

    @probe_app.get("/probe/maintenance", operation_id="get_probe_maintenance")
    def maintenance() -> None:
        raise HTTPException(503, "down for maintenance", headers={"Retry-After": "30"})

    response = TestClient(probe_app).get("/probe/maintenance")

    events = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.startswith("{")]
    [completed] = [e for e in events if e["event"] == "request_completed"]
    assert response.status_code == 503
    assert response.headers["Retry-After"] == "30"
    assert completed["level"] == "error"
