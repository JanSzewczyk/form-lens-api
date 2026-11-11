"""Two documents at a time, and a third is told to come back: proved with competing requests."""

import sys
import threading
import time
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from formlens.config import Settings
from formlens.main import create_app
from formlens.parsing.exceptions import ParseFailed, ParserBusy
from formlens.parsing.slots import ParseSlots
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
def settings(db_url: str) -> Settings:
    return make_settings(max_concurrency=SLOTS, db_url=db_url)


def post_png(client: TestClient) -> int:
    return client.post(URL, files={"file": ("a.png", sample("sample.png"), "image/png")}).status_code


@pytest.mark.concurrency
def test_only_two_of_five_simultaneous_documents_are_parsed_and_the_rest_are_told_to_retry(app: FastAPI) -> None:
    release = threading.Event()
    parser = FakeParser(release=release)
    app.state.parser = parser  # not a dependency override: those are rebuilt on every request
    warm_up(app)  # the first request builds the OpenAPI document; do not let five threads do it together
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


@pytest.fixture
def frequent_thread_switches() -> Iterator[None]:
    """Let the interpreter hand the GIL over every microsecond, so a gap between a check and a take is hit."""
    interval = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)
    yield
    sys.setswitchinterval(interval)


class Race:
    """One round: `callers` threads ask the same slots at the same moment.

    A caller that gets a slot keeps it until every caller has either entered or been refused, so the
    callers really are inside together; a guard that lets too many in shows as a wrong count, not as a hang.
    """

    def __init__(self, slots: ParseSlots, callers: int) -> None:
        self.slots = slots
        self.callers = callers
        self.entered = 0
        self.refused = 0
        self.inside = 0
        self.most_inside = 0
        self._barrier = threading.Barrier(callers, timeout=5)
        self._lock = threading.Lock()
        self._decided = threading.Event()

    def _count(self, *, entered: bool) -> None:
        with self._lock:
            if entered:
                self.entered += 1
                self.inside += 1
                self.most_inside = max(self.most_inside, self.inside)
            else:
                self.refused += 1
            if self.entered + self.refused == self.callers:
                self._decided.set()

    def attempt(self, _: int) -> None:
        self._barrier.wait()
        try:
            with self.slots.hold():
                self._count(entered=True)
                self._decided.wait(2)
                with self._lock:
                    self.inside -= 1
        except ParserBusy:
            self._count(entered=False)

    def run(self) -> tuple[int, int, int]:
        with ThreadPoolExecutor(self.callers) as pool:
            list(pool.map(self.attempt, range(self.callers)))
        return self.entered, self.refused, self.most_inside


def contend(slots: ParseSlots, callers: int, *, rounds: int = 1) -> list[tuple[int, int, int]]:
    """Run `rounds` races on the same slots; each gives (entered, refused, most inside at once)."""
    return [Race(slots, callers).run() for _ in range(rounds)]


@pytest.mark.concurrency
@pytest.mark.parametrize("round_number", range(10), ids=lambda n: f"round-{n}")
def test_exactly_as_many_callers_as_slots_get_in_when_eight_ask_at_once(
    frequent_thread_switches: None, round_number: int
) -> None:
    [outcome] = contend(ParseSlots(SLOTS), 8)  # fresh slots every round

    assert outcome == (SLOTS, 8 - SLOTS, SLOTS)


@pytest.mark.concurrency
def test_the_slots_are_whole_again_after_each_of_three_hundred_rounds_of_eight_callers(
    frequent_thread_switches: None,
) -> None:
    """Many rounds on the same slots: a leaked or doubled slot shows in a later round.

    This does NOT detect a plain non-atomic counter on the GIL build: `if free > 0: free -= 1` passed
    20 of 20 runs of the shipped tests there (only a mutant whose window a sleep widens fails). A gap
    between "is one free" and "take it" can be hit on the free-threaded build, whose CI job is switched off.
    """
    outcomes = contend(ParseSlots(SLOTS), 8, rounds=300)

    assert outcomes == [(SLOTS, 8 - SLOTS, SLOTS)] * 300


def warm_up(app: FastAPI) -> None:
    """Answer one request alone first: the first request builds the OpenAPI document (the repeated-query check
    reads it) in a worker thread, and several threads doing that together can trip a Pydantic warning that
    `filterwarnings = error` turns into a 500."""
    assert TestClient(app).get("/health").status_code == 200


def fire(app: FastAPI) -> tuple[list[int], FakeParser, bool]:
    """Send `THREADS` requests together and hold the parser until each is inside it or already answered."""
    release = threading.Event()
    parser = FakeParser(release=release)
    app.state.parser = parser  # not a dependency override: FastAPI rebuilds an override's dependants on every request
    barrier = threading.Barrier(THREADS, timeout=5)
    answered: list[int] = []

    def send(_: int) -> int:
        client = TestClient(app)
        barrier.wait()
        status = client.post(URL, files={"file": ("a.png", sample("sample.png"), "image/png")}).status_code
        answered.append(status)
        return status

    with ThreadPoolExecutor(THREADS) as pool:
        futures = [pool.submit(send, i) for i in range(THREADS)]
        settled = wait_until(lambda: parser.running + len(answered) == THREADS)
        release.set()
        statuses = [future.result(timeout=10) for future in futures]
    return statuses, parser, settled


@pytest.mark.concurrency
def test_the_same_app_refuses_the_same_number_of_requests_in_every_round(
    app: FastAPI, frequent_thread_switches: None
) -> None:
    warm_up(app)

    rounds = [fire(app) for _ in range(6)]  # one app: a slot the first round kept would shrink the later ones

    assert all(settled for _, _, settled in rounds)
    assert [sorted(statuses) for statuses, _, _ in rounds] == [[200, 200, 503, 503, 503]] * 6
    assert [parser.max_running for _, parser, _ in rounds] == [SLOTS] * 6
