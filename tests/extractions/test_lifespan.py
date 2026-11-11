"""Starting and stopping the app: the head check, recovery, the worker and the time it takes to stop."""

import asyncio
import json
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from formlens.config import Settings
from formlens.database import Database
from formlens.extractions.adapters.sqlite_repository import SqliteExtractionRepository
from formlens.extractions.domain.model import ExtractionStatus
from formlens.extractions.entrypoints.worker import ExtractionWorker
from formlens.main import create_app
from formlens.migrations import DatabaseNotAtHead
from formlens.parsing.exceptions import ParserBusy
from tests.conftest import make_settings
from tests.documents import sample
from tests.extractions.factories import ExtractionFactory
from tests.extractions.fakes import FakeExtractor
from tests.extractions.harness import Harness, wait_until
from tests.fakes import FakeParser

PDF = sample("text_layer.pdf")
NOW = datetime.now(UTC)


@contextmanager
def running_app(settings: Settings, extractor: FakeExtractor, **kwargs: Any) -> Iterator[tuple[FastAPI, TestClient]]:
    app = create_app(settings, parser_factory=lambda _: FakeParser(), extractor_factory=lambda _: extractor, **kwargs)
    try:
        with TestClient(app) as client:
            yield app, client
    finally:
        app.state.database.dispose()


def template(client: TestClient) -> str:
    body = {"name": "T", "fields": [{"name": "number", "type": "text", "required": True}]}
    return str(client.post("/v1/templates", json=body).json()["id"])


def submit(client: TestClient, template_id: str) -> str:
    response = client.post(
        "/v1/extractions", data={"template_id": template_id}, files={"file": ("a.pdf", PDF, "application/pdf")}
    )
    assert response.status_code == 202
    return str(response.headers["Location"])


def status_of(client: TestClient, location: str) -> str:
    return str(client.get(location).json()["status"])


@pytest.fixture
def fast(db_url: str) -> Settings:
    return make_settings(db_url=db_url, job_poll_interval_seconds=0.02)


# --- head check ------------------------------------------------------------------------------------


def test_a_database_that_is_not_migrated_stops_the_start_with_a_hint_before_the_model_loads(
    tmp_path: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    loaded: list[int] = []

    def factory(_: Settings) -> FakeParser:
        loaded.append(1)
        return FakeParser()

    app = create_app(
        make_settings(db_url=f"sqlite:///{tmp_path / 'empty.db'}"),
        parser_factory=factory,
        extractor_factory=lambda _: FakeExtractor(),
        start_worker=False,
    )

    with pytest.raises(DatabaseNotAtHead), TestClient(app):
        pass

    [line] = [
        json.loads(x)
        for x in capsys.readouterr().out.splitlines()
        if x.startswith("{") and "database_not_migrated" in x
    ]
    assert (line["level"], line["current"], line["head"]) == ("error", None, "0001")
    assert "make migrate" in line["hint"]
    assert loaded == []  # checked first: a missing migration is known before the model has loaded


def test_a_migrated_database_starts_and_serves(fast: Settings) -> None:
    with running_app(fast, FakeExtractor(), start_worker=False) as (_, client):
        assert client.get("/health").status_code == 200


# --- the worker ------------------------------------------------------------------------------------


def test_the_worker_takes_a_queued_job_and_completes_it_by_itself(fast: Settings) -> None:
    with running_app(fast, FakeExtractor({"number": "INV-1"})) as (_, client):
        location = submit(client, template(client))

        assert wait_until(lambda: status_of(client, location) == "completed")

        done = client.get(location).json()
        assert (done["attempts"], done["result"]) == (1, {"number": "INV-1"})


def test_a_job_the_service_left_running_is_recovered_at_start_and_completes_with_its_second_attempt(
    fast: Settings, db_url: str
) -> None:
    with running_app(fast, FakeExtractor(), start_worker=False) as (_, client):
        template_id = template(client)
    database = Database(db_url)
    try:
        repository = SqliteExtractionRepository(database)
        stuck = ExtractionFactory.build(template__template_id=UUID(template_id), created_at=NOW)
        repository.add(stuck, PDF, max_pending=10)
        assert repository.claim_next(NOW) is not None  # the service stopped here, with the job running
    finally:
        database.dispose()

    with running_app(fast, FakeExtractor({"number": "INV-2"})) as (_, client):
        location = f"/v1/extractions/{stuck.id}"

        assert wait_until(lambda: status_of(client, location) == "completed")

        done = client.get(location).json()
        assert (done["attempts"], done["result"]) == (2, {"number": "INV-2", "buyer": None})  # the copy has two fields


def test_a_job_that_used_every_attempt_before_the_stop_fails_as_interrupted_at_start(
    db_url: str,
) -> None:
    settings = make_settings(db_url=db_url, job_max_attempts=1, job_poll_interval_seconds=0.02)
    database = Database(db_url)
    try:
        repository = SqliteExtractionRepository(database)
        stuck = ExtractionFactory.build(created_at=NOW)
        repository.add(stuck, PDF, max_pending=10)
        repository.claim_next(NOW)
    finally:
        database.dispose()

    with running_app(settings, FakeExtractor(), start_worker=False) as (_, client):
        failed = client.get(f"/v1/extractions/{stuck.id}").json()

    assert (failed["status"], failed["error"]["reason"]) == ("failed", "interrupted")


def test_the_worker_purges_what_expired_at_start(fast: Settings, db_url: str) -> None:
    database = Database(db_url)
    try:
        repository = SqliteExtractionRepository(database)
        old = ExtractionFactory.build(created_at=NOW - timedelta(days=3))
        repository.add(old, PDF, max_pending=10)
        taken = repository.claim_next(NOW)
        assert taken is not None
        repository.finish_if_running(taken.complete({}, NOW - timedelta(days=2)))
    finally:
        database.dispose()

    with running_app(fast, FakeExtractor()) as (app, _):
        assert wait_until(lambda: app.state.extraction_repository.get(old.id) is None)


def test_a_crash_in_the_loop_is_logged_once_by_type_and_the_worker_goes_on(
    fast: Settings, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    app = create_app(
        fast, parser_factory=lambda _: FakeParser(), extractor_factory=lambda _: FakeExtractor({"number": "ok"})
    )
    original: dict[str, Callable[[], bool]] = {}
    crashed = threading.Event()

    def flaky_run_once() -> bool:
        if not crashed.is_set():
            crashed.set()
            raise RuntimeError("storage said PRIVATE-TEXT-9")
        return original["run_once"]()

    try:
        with TestClient(app) as client:
            processor = app.state.extraction_processor
            original["run_once"] = processor.run_once
            monkeypatch.setattr(processor, "run_once", flaky_run_once)
            location = submit(client, template(client))

            assert wait_until(lambda: status_of(client, location) == "completed")
    finally:
        app.state.database.dispose()

    out = capsys.readouterr().out
    lines = [json.loads(x) for x in out.splitlines() if x.startswith("{") and "extraction_worker_crashed" in x]
    assert len(lines) == 1
    assert (lines[0]["step"], lines[0]["cause_type"]) == ("job", "RuntimeError")
    assert "PRIVATE-TEXT-9" not in out


# --- stopping --------------------------------------------------------------------------------------


def test_an_idle_worker_stops_at_once_even_with_a_long_poll_interval(db_url: str) -> None:
    settings = make_settings(db_url=db_url, job_poll_interval_seconds=30)
    app = create_app(settings, parser_factory=lambda _: FakeParser(), extractor_factory=lambda _: FakeExtractor())
    try:
        client = TestClient(app)
        client.__enter__()
        time.sleep(0.1)  # the loop is waiting out its poll interval
        started = time.perf_counter()
        client.__exit__(None, None, None)
        took = time.perf_counter() - started
    finally:
        app.state.database.dispose()

    assert took < 2.0


def test_a_job_that_is_still_running_does_not_hold_the_shutdown_past_its_budget(db_url: str) -> None:
    release = threading.Event()
    extractor = FakeExtractor({"number": "late"}, release=release)
    settings = make_settings(db_url=db_url, job_poll_interval_seconds=0.02, graceful_shutdown_seconds=3)
    app = create_app(settings, parser_factory=lambda _: FakeParser(), extractor_factory=lambda _: extractor)
    stuck: UUID | None = None
    try:
        client = TestClient(app)
        client.__enter__()
        location = submit(client, template(client))
        stuck = UUID(location.rsplit("/", 1)[1])
        assert wait_until(extractor.started.is_set)
        started = time.perf_counter()
        client.__exit__(None, None, None)
        took = time.perf_counter() - started
    finally:
        release.set()
        assert stuck is not None
        # The abandoned thread finishes its job and writes into the same file: wait for it, then let go of the file.
        assert wait_until(lambda: app.state.extraction_repository.get(stuck).status is ExtractionStatus.COMPLETED)
        app.state.database.dispose()

    assert took < 3.0  # the budget is 3 s of which 2 s are the margin: the worker waits at most 1 s


def test_an_app_built_with_the_default_extractor_starts_serves_health_and_stops(db_url: str) -> None:
    app = create_app(make_settings(db_url=db_url), parser_factory=lambda _: FakeParser(), start_worker=False)
    try:
        with TestClient(app) as client:
            assert client.get("/health").status_code == 200
    finally:
        app.state.database.dispose()


class CountingRepository(SqliteExtractionRepository):
    """The SQLite repository that counts how many times the purge ran."""

    purges = 0

    def purge_before(self, cutoff: datetime) -> int:
        type(self).purges += 1
        return super().purge_before(cutoff)


def test_a_running_worker_purges_expired_extractions_on_its_own_schedule(database: Database) -> None:
    """The purge runs about once a minute; here the interval is short, so a result that expires later is gone too."""
    CountingRepository.purges = 0
    repository = CountingRepository(database)
    harness = Harness(repository=repository, ttl=timedelta(hours=1))
    extraction = harness.submit()
    claimed = repository.claim_next(harness.clock.now)
    assert claimed is not None
    repository.finish_if_running(claimed.complete({"number": "x", "buyer": None}, harness.clock.now))
    worker = ExtractionWorker(harness.processor, poll_interval_seconds=0.01, purge_interval_seconds=0.01)

    async def until(condition: Callable[[], bool]) -> bool:
        for _ in range(500):
            if condition():
                return True
            await asyncio.sleep(0.01)
        return condition()

    async def run() -> tuple[bool, bool]:
        worker.start()
        purged_at_start_and_once_more = await until(lambda: CountingRepository.purges >= 2)
        harness.clock.advance(hours=2)  # the result is now past its time to live
        gone = await until(lambda: repository.get(extraction.id) is None)
        await worker.stop(5)
        return purged_at_start_and_once_more, gone

    ran_again, gone = asyncio.run(run())

    assert (ran_again, gone) == (True, True)


# --- a busy parser ---------------------------------------------------------------------------------


def test_a_parser_that_stays_busy_does_not_make_the_worker_spin_and_the_job_completes_when_it_frees_up(
    db_url: str, capsys: pytest.CaptureFixture[str]
) -> None:
    parser = FakeParser(error=ParserBusy())  # every document finds the parser full
    settings = make_settings(db_url=db_url, job_poll_interval_seconds=0.2)
    app = create_app(
        settings, parser_factory=lambda _: parser, extractor_factory=lambda _: FakeExtractor({"number": "ok"})
    )
    try:
        with TestClient(app) as client:
            location = submit(client, template(client))

            time.sleep(1.0)
            busy_calls = len(parser.calls)
            claims = capsys.readouterr().out.count('"extraction_claimed"')
            still_waiting = client.get(location).json()

            parser.error = None  # the slot is free again
            assert wait_until(lambda: status_of(client, location) == "completed", timeout=5.0)
            done = client.get(location).json()
    finally:
        app.state.database.dispose()

    # About one try per poll interval (5 in a second); a spinning worker made about a thousand.
    assert 1 <= busy_calls <= 15
    assert 1 <= claims <= 15
    assert (still_waiting["status"], still_waiting["attempts"]) == ("pending", 0)  # the attempt is not used
    assert (done["status"], done["attempts"], done["result"]) == ("completed", 1, {"number": "ok"})
