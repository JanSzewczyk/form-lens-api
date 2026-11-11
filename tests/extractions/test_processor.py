"""The worker's step, driven by hand: every way a job can end, with a fake clock and fakes that can be held."""

import threading
from datetime import timedelta

import pytest
from structlog.testing import capture_logs

from formlens.database import Database
from formlens.extractions.adapters.sqlite_repository import SqliteExtractionRepository
from formlens.extractions.domain.exceptions import (
    DocumentTooLong,
    FileUnreadable,
    InvalidOutput,
    LlmUnavailable,
    ParseFailed,
    ParserBusy,
)
from formlens.extractions.domain.model import FAILURE_MESSAGES, ExtractionStatus, FailureReason
from tests.extractions.fakes import FakeExtractionRepository, FakeExtractor, FakeTextSource
from tests.extractions.harness import Harness, wait_until

VALUES = {"number": "INV-42", "buyer": None}


def test_a_job_goes_from_pending_through_running_to_completed() -> None:
    harness = Harness(extractor=FakeExtractor(VALUES))
    extraction = harness.submit()
    assert harness.stored(extraction).status is ExtractionStatus.PENDING

    assert harness.processor.run_once() is True

    done = harness.stored(extraction)
    assert done.status is ExtractionStatus.COMPLETED
    assert done.attempts == 1
    assert done.result == VALUES
    assert done.started_at is not None
    assert done.finished_at is not None
    assert done.error is None
    assert harness.repository.read_input(extraction.id) is None


def test_the_extractor_gets_the_text_and_the_copy_of_the_template() -> None:
    harness = Harness(text_source=FakeTextSource("twelve chars"), extractor=FakeExtractor(VALUES))
    extraction = harness.submit()

    harness.processor.run_once()

    assert harness.extractor.calls == [(len("twelve chars"), extraction.template.template_id)]


def test_with_nothing_waiting_the_step_does_nothing() -> None:
    assert Harness().processor.run_once() is False


def test_jobs_run_oldest_first_one_per_step() -> None:
    harness = Harness(extractor=FakeExtractor(VALUES))
    first, second = harness.submit(), harness.submit()

    harness.processor.run_once()

    assert harness.stored(first).status is ExtractionStatus.COMPLETED
    assert harness.stored(second).status is ExtractionStatus.PENDING


def test_a_completed_result_reports_the_required_fields_that_came_back_null() -> None:
    harness = Harness(extractor=FakeExtractor({"number": None, "buyer": "ACME"}))
    extraction = harness.submit()

    harness.processor.run_once()

    done = harness.stored(extraction)
    assert done.status is ExtractionStatus.COMPLETED  # a null in a required field is not a failure (D15)
    assert done.missing_required == ["number"]


# --- time limit ------------------------------------------------------------------------------------


def test_a_job_that_runs_out_of_time_fails_as_timed_out_and_its_late_result_is_discarded() -> None:
    release = threading.Event()
    harness = Harness(extractor=FakeExtractor(VALUES, release=release), job_timeout_seconds=0.05)
    extraction = harness.submit()

    try:
        assert harness.processor.run_once() is True
        timed_out = harness.stored(extraction)
        assert harness.deadline.busy() is True  # the conversion is still alive
    finally:
        release.set()
    assert wait_until(harness.extractor.finished.is_set)
    assert wait_until(lambda: not harness.deadline.busy())

    assert timed_out.status is ExtractionStatus.FAILED
    assert timed_out.error is not None
    assert timed_out.error.reason is FailureReason.TIMED_OUT
    assert timed_out.error.message == FAILURE_MESSAGES[FailureReason.TIMED_OUT]
    assert harness.stored(extraction) == timed_out  # the late result changed nothing
    assert harness.stored(extraction).result is None


def test_a_timeout_is_not_retried_even_with_attempts_left() -> None:
    release = threading.Event()
    harness = Harness(extractor=FakeExtractor(release=release), job_timeout_seconds=0.05, max_attempts=5)
    extraction = harness.submit()

    try:
        harness.processor.run_once()
    finally:
        release.set()

    failed = harness.stored(extraction)
    assert (failed.status, failed.attempts) == (ExtractionStatus.FAILED, 1)


def test_nothing_is_claimed_while_a_timed_out_conversion_is_still_running_and_the_next_job_starts_after_it() -> None:
    release = threading.Event()
    extractor = FakeExtractor(VALUES, release=release)
    harness = Harness(extractor=extractor, job_timeout_seconds=0.05)
    first, second = harness.submit(), harness.submit()
    harness.processor.run_once()
    assert harness.deadline.busy()

    claimed_while_busy = harness.processor.run_once()

    assert claimed_while_busy is False
    waiting = harness.stored(second)
    assert (waiting.status, waiting.attempts) == (ExtractionStatus.PENDING, 0)
    release.set()
    assert wait_until(lambda: not harness.deadline.busy())
    assert harness.processor.run_once() is True
    assert harness.stored(second).status is ExtractionStatus.COMPLETED
    assert harness.stored(first).status is ExtractionStatus.FAILED


# --- parser busy -----------------------------------------------------------------------------------


def test_a_busy_parser_puts_the_job_back_and_the_attempt_is_not_used() -> None:
    harness = Harness(text_source=FakeTextSource(errors=[ParserBusy()]), extractor=FakeExtractor(VALUES))
    extraction = harness.submit()

    assert harness.processor.run_once() is True

    waiting = harness.stored(extraction)
    assert (waiting.status, waiting.attempts) == (ExtractionStatus.PENDING, 0)
    assert harness.repository.read_input(extraction.id) is not None
    assert harness.processor.run_once() is True
    done = harness.stored(extraction)
    assert (done.status, done.attempts) == (ExtractionStatus.COMPLETED, 1)


def test_a_parser_that_stays_busy_never_uses_up_the_attempts() -> None:
    harness = Harness(text_source=FakeTextSource(errors=[ParserBusy()] * 5), max_attempts=2)
    extraction = harness.submit()

    for _ in range(5):
        harness.processor.run_once()

    waiting = harness.stored(extraction)
    assert (waiting.status, waiting.attempts) == (ExtractionStatus.PENDING, 0)


# --- retries (D8) ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (ParseFailed(), FailureReason.PARSE_FAILED),
        (LlmUnavailable(), FailureReason.LLM_UNAVAILABLE),
        (InvalidOutput(), FailureReason.INVALID_OUTPUT),
    ],
    ids=["parse-failed", "llm-unavailable", "invalid-output"],
)
def test_a_failure_a_second_try_may_cure_is_retried_and_ends_when_the_attempts_are_used_up(
    error: Exception, reason: FailureReason
) -> None:
    harness = Harness(extractor=FakeExtractor(errors=[error, type(error)()]), max_attempts=2)
    extraction = harness.submit()

    harness.processor.run_once()
    after_first = harness.stored(extraction)
    harness.processor.run_once()
    after_second = harness.stored(extraction)

    assert (after_first.status, after_first.attempts) == (ExtractionStatus.PENDING, 1)
    assert (after_second.status, after_second.attempts) == (ExtractionStatus.FAILED, 2)
    assert after_second.error is not None
    assert (after_second.error.reason, after_second.error.message) == (reason, FAILURE_MESSAGES[reason])
    assert harness.repository.read_input(extraction.id) is None


def test_a_job_that_fails_once_and_then_works_completes_on_its_second_attempt() -> None:
    harness = Harness(extractor=FakeExtractor(VALUES, errors=[LlmUnavailable()]))
    extraction = harness.submit()

    harness.processor.run_once()
    harness.processor.run_once()

    done = harness.stored(extraction)
    assert (done.status, done.attempts, done.result) == (ExtractionStatus.COMPLETED, 2, VALUES)


def test_one_attempt_allowed_means_the_first_failure_is_final() -> None:
    harness = Harness(extractor=FakeExtractor(errors=[LlmUnavailable()]), max_attempts=1)
    extraction = harness.submit()

    harness.processor.run_once()

    assert harness.stored(extraction).status is ExtractionStatus.FAILED


def test_an_unreadable_file_fails_at_once_with_attempts_left() -> None:
    harness = Harness(text_source=FakeTextSource(errors=[FileUnreadable()]), max_attempts=5)
    extraction = harness.submit()

    harness.processor.run_once()

    failed = harness.stored(extraction)
    assert (failed.status, failed.attempts) == (ExtractionStatus.FAILED, 1)
    assert failed.error is not None
    assert failed.error.reason is FailureReason.INVALID_FILE


def test_a_text_longer_than_the_limit_fails_as_too_long_without_calling_the_model() -> None:
    harness = Harness(text_source=FakeTextSource("x" * 11), max_input_chars=10, max_attempts=5)
    extraction = harness.submit()

    harness.processor.run_once()

    failed = harness.stored(extraction)
    assert failed.error is not None
    assert failed.error.reason is FailureReason.DOCUMENT_TOO_LONG
    assert failed.attempts == 1
    assert harness.extractor.calls == []


def test_a_text_of_exactly_the_limit_is_given_to_the_model() -> None:
    harness = Harness(text_source=FakeTextSource("x" * 10), max_input_chars=10, extractor=FakeExtractor(VALUES))
    extraction = harness.submit()

    harness.processor.run_once()

    assert harness.stored(extraction).status is ExtractionStatus.COMPLETED


def test_the_port_that_raises_document_too_long_itself_ends_the_job_the_same_way() -> None:
    harness = Harness(extractor=FakeExtractor(errors=[DocumentTooLong()]), max_attempts=5)
    extraction = harness.submit()

    harness.processor.run_once()

    failed = harness.stored(extraction)
    assert failed.error is not None
    assert failed.error.reason is FailureReason.DOCUMENT_TOO_LONG


def test_an_error_nobody_translated_ends_the_job_without_its_text_in_the_extraction_or_the_log() -> None:
    harness = Harness(extractor=FakeExtractor(errors=[RuntimeError("the form of Jan Kowalski, PESEL 44051401359")]))
    extraction = harness.submit()

    with capture_logs() as logs:
        harness.processor.run_once()

    failed = harness.stored(extraction)
    assert failed.error is not None
    assert failed.error.reason is FailureReason.INTERRUPTED
    assert failed.error.message == FAILURE_MESSAGES[FailureReason.INTERRUPTED]
    assert "Kowalski" not in str(logs)
    assert "Kowalski" not in repr(failed)
    [line] = [entry for entry in logs if entry["event"] == "extraction_finished"]
    assert line["cause_type"] == "RuntimeError"


def test_a_job_whose_upload_is_gone_ends_as_interrupted() -> None:
    harness = Harness()
    extraction = harness.submit()
    assert isinstance(harness.repository, FakeExtractionRepository)
    del harness.repository.inputs[extraction.id]

    harness.processor.run_once()

    failed = harness.stored(extraction)
    assert failed.error is not None
    assert failed.error.reason is FailureReason.INTERRUPTED


# --- recovery --------------------------------------------------------------------------------------


def test_after_a_restart_a_job_that_was_running_runs_again_and_completes() -> None:
    harness = Harness(extractor=FakeExtractor(VALUES))
    extraction = harness.submit()
    harness.repository.claim_next(harness.clock.now)  # the service stopped here

    harness.processor.recover()

    assert harness.stored(extraction).status is ExtractionStatus.PENDING
    harness.processor.run_once()
    done = harness.stored(extraction)
    assert (done.status, done.attempts) == (ExtractionStatus.COMPLETED, 2)


def test_after_a_restart_a_job_that_used_every_attempt_fails_as_interrupted() -> None:
    harness = Harness(max_attempts=1)
    extraction = harness.submit()
    harness.repository.claim_next(harness.clock.now)

    with capture_logs() as logs:
        harness.processor.recover()

    failed = harness.stored(extraction)
    assert failed.error is not None
    assert failed.error.reason is FailureReason.INTERRUPTED
    assert failed.finished_at == harness.clock.now
    assert harness.repository.read_input(extraction.id) is None
    [line] = [entry for entry in logs if entry["event"] == "extraction_recovered"]
    assert (line["requeued"], line["failed"]) == (0, 1)


def test_a_recovery_with_nothing_to_recover_logs_nothing() -> None:
    harness = Harness()
    harness.submit()

    with capture_logs() as logs:
        harness.processor.recover()

    assert logs == []


# --- retention -------------------------------------------------------------------------------------


def test_the_purge_deletes_finished_extractions_after_their_time_to_live_and_is_idempotent() -> None:
    harness = Harness(extractor=FakeExtractor(VALUES), ttl=timedelta(hours=2))
    done, waiting = harness.submit(), None
    harness.processor.run_once()
    waiting = harness.submit()
    harness.clock.advance(hours=1)
    assert harness.processor.purge_expired() == 0

    harness.clock.advance(hours=2)
    with capture_logs() as logs:
        first = harness.processor.purge_expired()
    second = harness.processor.purge_expired()

    assert (first, second) == (1, 0)
    assert harness.repository.get(done.id) is None
    assert harness.repository.get(waiting.id) is not None  # not finished: never purged
    [line] = [entry for entry in logs if entry["event"] == "extractions_purged"]
    assert line["count"] == 1


# --- logging ---------------------------------------------------------------------------------------


def test_the_lifecycle_logs_claim_and_finish_with_the_reason_and_the_time_but_no_text_or_value() -> None:
    harness = Harness(
        text_source=FakeTextSource("PRIVATE-TEXT-77"),
        extractor=FakeExtractor({"number": "PRIVATE-VALUE-88", "buyer": None}),
    )
    extraction = harness.submit()

    with capture_logs() as logs:
        harness.processor.run_once()

    events = [entry["event"] for entry in logs]
    assert events == ["extraction_claimed", "extraction_finished"]
    finished = logs[1]
    assert (finished["extraction_id"], finished["status"], finished["reason"]) == (
        str(extraction.id),
        "completed",
        None,
    )
    assert isinstance(finished["elapsed_ms"], int)
    assert "PRIVATE" not in str(logs)


# --- a restart while an old attempt is still running, on a real SQLite file -------------------------


def test_a_result_of_a_stopped_workers_attempt_cannot_end_the_attempt_that_took_over(database: Database) -> None:
    """The service stops with a job running, starts again and runs the job a second time; the first attempt's
    thread, left behind at the stop, finishes while the second is still running. Only the second may end the job."""
    repository = SqliteExtractionRepository(database)
    held_old, held_new = threading.Event(), threading.Event()
    old = Harness(repository=repository, extractor=FakeExtractor({"number": "OLD"}, release=held_old))
    new = Harness(repository=repository, extractor=FakeExtractor({"number": "NEW"}, release=held_new))
    extraction = old.submit()
    first = threading.Thread(target=old.processor.run_once, daemon=True)
    second = threading.Thread(target=new.processor.run_once, daemon=True)
    try:
        first.start()
        assert wait_until(old.extractor.started.is_set)  # attempt 1 is running; the service "stops" here
        new.processor.recover()
        assert repository.get(extraction.id).status is ExtractionStatus.PENDING  # type: ignore[union-attr]
        second.start()
        assert wait_until(new.extractor.started.is_set)  # attempt 2 is running
        held_old.set()  # the old attempt ends first
        first.join(5)
        mid = repository.get(extraction.id)
        held_new.set()
        second.join(5)
    finally:
        held_old.set()
        held_new.set()
    done = repository.get(extraction.id)

    assert mid is not None
    assert (mid.status, mid.attempts, mid.result) == (ExtractionStatus.RUNNING, 2, None)
    assert done is not None
    assert (done.status, done.attempts, done.result) == (
        ExtractionStatus.COMPLETED,
        2,
        {"number": "NEW", "buyer": None},
    )


def test_a_job_that_timed_out_stays_timed_out_through_a_restart_and_a_late_result_after_it(database: Database) -> None:
    repository = SqliteExtractionRepository(database)
    release = threading.Event()
    before = Harness(
        repository=repository, extractor=FakeExtractor({"number": "LATE"}, release=release), job_timeout_seconds=0.05
    )
    after = Harness(repository=repository, extractor=FakeExtractor({"number": "OK"}))
    timed_out, next_job = before.submit(), before.submit()
    try:
        before.processor.run_once()
        failed = repository.get(timed_out.id)
        after.processor.recover()  # the service restarted; the first job is not running any more
        recovered = repository.get(timed_out.id)
        assert after.processor.run_once() is True
        release.set()
        assert wait_until(before.extractor.finished.is_set)
        assert wait_until(lambda: not before.deadline.busy())
    finally:
        release.set()

    assert failed is not None
    assert (failed.status, failed.attempts) == (ExtractionStatus.FAILED, 1)
    assert recovered == failed  # a restart does not give a timed-out job another attempt
    final = repository.get(timed_out.id)
    assert final == failed
    assert final is not None
    assert final.result is None
    done = repository.get(next_job.id)
    assert done is not None
    assert (done.status, done.result) == (ExtractionStatus.COMPLETED, {"number": "OK", "buyer": None})
