"""The body cap, driven at the ASGI level so each chunk the framework pulls can be counted."""

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from starlette.types import Message, Receive, Scope, Send

from formlens.parsing.body_limit import SLACK_BYTES, BodyLimitMiddleware
from formlens.parsing.models import BYTES_PER_MB

PATH = "/v1/documents/parse"
OTHER_UPLOAD_PATH = "/v1/extractions"
PATHS = frozenset({PATH, OTHER_UPLOAD_PATH})
CAP = BYTES_PER_MB + SLACK_BYTES

type App = Callable[[Scope, Receive, Send], Awaitable[None]]


class Run:
    """What happened when a request went through the middleware."""

    def __init__(self) -> None:
        self.sent: list[Message] = []
        self.pulled = 0  # how many messages the client side was asked for

    @property
    def status(self) -> int:
        return int(next(m["status"] for m in self.sent if m["type"] == "http.response.start"))

    @property
    def body(self) -> dict[str, Any]:
        raw = b"".join(m.get("body", b"") for m in self.sent if m["type"] == "http.response.body")
        return dict(json.loads(raw))


def drive(
    app: App,
    chunks: list[bytes],
    *,
    method: str = "POST",
    path: str = PATH,
    headers: list[tuple[bytes, bytes]] | None = None,
) -> Run:
    run = Run()
    pending = list(chunks)
    middleware = BodyLimitMiddleware(app, paths=PATHS, max_upload_mb=1)

    async def receive() -> Message:
        if not pending:
            return {"type": "http.disconnect"}
        run.pulled += 1
        chunk = pending.pop(0)
        return {"type": "http.request", "body": chunk, "more_body": bool(pending)}

    async def send(message: Message) -> None:
        run.sent.append(message)

    scope: Scope = {
        "type": "http",
        "method": method,
        "path": path,
        "headers": headers or [],
        "state": {"request_id": "r-1"},
    }
    asyncio.run(middleware(scope, receive, send))
    return run


async def read_everything_and_answer_200(scope: Scope, receive: Receive, send: Send) -> None:
    while (await receive())["type"] == "http.request":
        pass
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"{}"})


def test_a_declared_length_over_the_cap_is_refused_before_a_single_byte_is_read() -> None:
    run = drive(read_everything_and_answer_200, [b"x"], headers=[(b"content-length", str(CAP + 1).encode())])

    assert run.status == 413
    assert run.pulled == 0
    assert run.body["type"] == "urn:problem:formlens:file-too-large"
    assert run.body["request_id"] == "r-1"


def test_a_declared_length_of_exactly_the_cap_goes_through() -> None:
    run = drive(read_everything_and_answer_200, [b"x"], headers=[(b"content-length", str(CAP).encode())])

    assert run.status == 200


def test_a_body_without_a_length_is_cut_when_the_count_passes_the_cap_and_the_rest_is_never_pulled() -> None:
    chunks = [bytes(256 * 1024)] * 16  # 4 MiB, far over the 2 MiB cap

    run = drive(read_everything_and_answer_200, chunks)

    assert run.status == 413
    assert run.pulled == 9  # 8 chunks fit the cap exactly; the ninth crosses it, and nothing after is pulled
    assert run.body["type"] == "urn:problem:formlens:file-too-large"


def test_a_chunked_body_of_exactly_the_cap_goes_through() -> None:
    run = drive(read_everything_and_answer_200, [bytes(256 * 1024)] * 8)

    assert run.status == 200


def test_the_answer_of_the_application_to_a_cut_body_is_replaced_by_the_413() -> None:
    async def answers_400_after_the_disconnect(scope: Scope, receive: Receive, send: Send) -> None:
        while (await receive())["type"] == "http.request":
            pass
        await send({"type": "http.response.start", "status": 400, "headers": []})
        await send({"type": "http.response.body", "body": b"{}"})

    run = drive(answers_400_after_the_disconnect, [bytes(CAP), b"x"])

    assert [m["status"] for m in run.sent if m["type"] == "http.response.start"] == [413]


def test_an_exception_of_the_application_on_a_cut_body_is_a_413_too() -> None:
    async def raises_on_disconnect(scope: Scope, receive: Receive, send: Send) -> None:
        while (await receive())["type"] == "http.request":
            pass
        raise RuntimeError("client went away")

    run = drive(raises_on_disconnect, [bytes(CAP), b"x"])

    assert run.status == 413


def test_an_exception_of_the_application_on_a_body_within_the_cap_is_not_hidden() -> None:
    async def raises(scope: Scope, receive: Receive, send: Send) -> None:
        raise RuntimeError("a bug")

    with pytest.raises(RuntimeError, match="a bug"):
        drive(raises, [b"x"])


def test_the_application_that_ends_without_answering_a_cut_body_still_gets_the_413() -> None:
    async def silent(scope: Scope, receive: Receive, send: Send) -> None:
        while (await receive())["type"] == "http.request":
            pass

    run = drive(silent, [bytes(CAP), b"x"])

    assert run.status == 413


@pytest.mark.parametrize("path", [PATH, OTHER_UPLOAD_PATH], ids=["parse", "second-upload-path"])
def test_every_listed_path_is_capped_by_its_declared_length(path: str) -> None:
    run = drive(read_everything_and_answer_200, [b"x"], path=path, headers=[(b"content-length", str(CAP + 1).encode())])

    assert run.status == 413
    assert run.pulled == 0


@pytest.mark.parametrize("path", [PATH, OTHER_UPLOAD_PATH], ids=["parse", "second-upload-path"])
def test_every_listed_path_is_capped_by_the_bytes_that_arrive(path: str) -> None:
    run = drive(read_everything_and_answer_200, [bytes(CAP), b"x", b"y"], path=path)

    assert run.status == 413
    assert run.pulled == 2


def test_a_middleware_given_no_paths_guards_nothing() -> None:
    reached: list[int] = []

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        reached.append(1)
        await send({"type": "http.response.start", "status": 200, "headers": []})

    sent: list[Message] = []

    async def collect(message: Message) -> None:
        sent.append(message)

    async def never(*_: Any) -> Any:
        raise AssertionError("not called")

    middleware = BodyLimitMiddleware(app, paths=frozenset(), max_upload_mb=1)
    scope: Scope = {
        "type": "http",
        "method": "POST",
        "path": PATH,
        "headers": [(b"content-length", str(10 * CAP).encode())],
    }
    asyncio.run(middleware(scope, never, collect))

    assert (reached, sent[0]["status"]) == ([1], 200)


@pytest.mark.parametrize(
    ("method", "path"),
    [("GET", PATH), ("PUT", PATH), ("GET", OTHER_UPLOAD_PATH), ("POST", "/v1/documents/other"), ("POST", "/health")],
)
def test_every_other_request_is_passed_through_whatever_its_size(method: str, path: str) -> None:
    run = drive(
        read_everything_and_answer_200,
        [bytes(CAP), bytes(CAP)],
        method=method,
        path=path,
        headers=[(b"content-length", str(10 * CAP).encode())],
    )

    assert run.status == 200
    assert run.pulled == 2


def test_a_content_length_that_is_not_a_number_is_left_to_the_server() -> None:
    run = drive(read_everything_and_answer_200, [b"x"], headers=[(b"content-length", b"abc")])

    assert run.status == 200


def test_a_websocket_scope_is_passed_through() -> None:
    reached: list[str] = []

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        reached.append(scope["type"])

    middleware = BodyLimitMiddleware(app, paths=PATHS, max_upload_mb=1)

    async def never(*_: Any) -> Any:
        raise AssertionError("not called")

    asyncio.run(middleware({"type": "websocket", "path": PATH}, never, never))

    assert reached == ["websocket"]


def test_a_framework_that_keeps_reading_after_the_cut_hears_a_disconnect_again_and_pulls_nothing_more() -> None:
    heard: list[str] = []

    async def reads_four_times(scope: Scope, receive: Receive, send: Send) -> None:
        first, second, third, fourth = await receive(), await receive(), await receive(), await receive()
        heard.extend(message["type"] for message in (first, second, third, fourth))
        await send({"type": "http.response.start", "status": 200, "headers": []})

    run = drive(reads_four_times, [bytes(CAP), b"x", b"y", b"z"])

    assert heard == ["http.request", "http.disconnect", "http.disconnect", "http.disconnect"]
    assert run.pulled == 2
    assert run.status == 413


@pytest.mark.parametrize(
    "length",
    [b"\xb2", b"\xb3\xb9", b"1\xb2"],
    ids=["superscript-two", "superscript-three-one", "digit-and-superscript"],
)
def test_a_content_length_that_only_looks_like_a_number_is_left_to_the_server(length: bytes) -> None:
    """`str.isdigit` is true for "²" (a header byte is read as Latin-1), but `int()` cannot read it."""
    run = drive(read_everything_and_answer_200, [b"x"], headers=[(b"content-length", length)])

    assert run.status == 200
