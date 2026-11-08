"""Two documents at a time, and a third is told to come back: proved with competing requests."""

import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from formlens.config import Settings
from formlens.main import create_app
from formlens.parsing.dependencies import get_parser
from formlens.parsing.exceptions import ParseFailed
from tests.conftest import make_settings
from tests.documents import sample
from tests.fakes import FakeParser

URL = "/v1/documents/parse"
THREADS = 5
SLOTS = 2


def wait_until(condition: Callable[[], bool], *, timeout: float = 5.0) -> bool:
    """Poll until `condition` holds; False when it never did within `timeout`."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.005)
    return condition()


@pytest.fixture
def settings() -> Settings:
    return make_settings(max_concurrency=SLOTS)


def post_png(client: TestClient) -> int:
    return client.post(URL, files={"file": ("a.png", sample("sample.png"), "image/png")}).status_code


@pytest.mark.concurrency
def test_only_two_of_five_simultaneous_documents_are_parsed_and_the_rest_are_told_to_retry(app: FastAPI) -> None:
    release = threading.Event()
    parser = FakeParser(release=release)
    app.dependency_overrides[get_parser] = lambda: parser
    barrier = threading.Barrier(THREADS, timeout=5)
    answered: list[int] = []
    retry_after: list[str | None] = []

    def send(_: int) -> int:
        client = TestClient(app)  # one client per thread; no lifespan, the parser is overridden
        barrier.wait()
        response = client.post(URL, files={"file": ("a.png", sample("sample.png"), "image/png")})
        if response.status_code == 503:
            retry_after.append(response.headers.get("Retry-After"))
        answered.append(response.status_code)
        return response.status_code

    with ThreadPoolExecutor(THREADS) as pool:
        futures = [pool.submit(send, i) for i in range(THREADS)]
        # Hold the parser until every request is either inside it or already answered. With the guard
        # that is 2 inside and 3 answered; without it all 5 are inside, so a broken guard fails the
        # assertions below instead of timing out here.
        settled = wait_until(lambda: parser.running + len(answered) == THREADS)
        release.set()
        statuses = [future.result(timeout=10) for future in futures]

    assert settled, f"running={parser.running} answered={answered}"
    assert sorted(statuses) == [200, 200, 503, 503, 503]
    assert parser.max_running == SLOTS
    assert retry_after == ["5", "5", "5"]
    assert post_png(TestClient(app)) == 200  # the slots were given back


def test_a_parser_that_raises_gives_its_slot_back() -> None:
    parser = FakeParser(error=ParseFailed())
    app = create_app(make_settings(max_concurrency=1), parser_factory=lambda _: parser)
    client = TestClient(app)
    app.state.parser = parser

    statuses = [post_png(client) for _ in range(3)]

    assert statuses == [500, 500, 500]  # never 503: each call found the single slot free
    assert len(parser.calls) == 3


def test_a_parser_that_raises_something_unexpected_gives_its_slot_back() -> None:
    parser = FakeParser(error=RuntimeError("model crashed"))
    app = create_app(make_settings(max_concurrency=1), parser_factory=lambda _: parser)
    app.state.parser = parser
    client = TestClient(app, raise_server_exceptions=False)

    statuses = [post_png(client) for _ in range(3)]

    assert statuses == [500, 500, 500]
    assert len(parser.calls) == 3
