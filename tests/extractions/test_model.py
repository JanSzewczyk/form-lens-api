"""The life of an extraction: what each move does and which ones are refused."""

from collections.abc import Callable
from datetime import timedelta
from uuid import UUID

import pytest

from formlens.extractions.domain.exceptions import InvalidTransition
from formlens.extractions.domain.model import (
    FAILURE_MESSAGES,
    TERMINAL_REASONS,
    Extraction,
    ExtractionStatus,
    FailureReason,
)
from tests.extractions.factories import NOW, ExtractionFactory, SnapshotFieldFactory, TemplateSnapshotFactory


def running(**overrides: object) -> Extraction:
    return ExtractionFactory.build(**overrides).claim(NOW)


def test_a_new_extraction_waits_with_no_attempt_used() -> None:
    extraction = Extraction.new(UUID(int=5), TemplateSnapshotFactory.build(), NOW)

    assert (extraction.status, extraction.attempts, extraction.created_at) == (ExtractionStatus.PENDING, 0, NOW)
    assert (extraction.started_at, extraction.finished_at, extraction.result, extraction.error) == (None,) * 4


def test_claiming_counts_the_attempt_and_stamps_the_start() -> None:
    later = NOW + timedelta(seconds=3)

    claimed = ExtractionFactory.build(attempts=1).claim(later)

    assert (claimed.status, claimed.attempts, claimed.started_at) == (ExtractionStatus.RUNNING, 2, later)


def test_completing_stores_the_result_and_the_end_time() -> None:
    done = running().complete({"number": "42", "buyer": None}, NOW + timedelta(seconds=9))

    assert done.status is ExtractionStatus.COMPLETED
    assert done.result == {"number": "42", "buyer": None}
    assert done.finished_at == NOW + timedelta(seconds=9)
    assert done.is_finished


@pytest.mark.parametrize("reason", list(FailureReason))
def test_failing_stores_the_reason_with_its_fixed_message(reason: FailureReason) -> None:
    failed = running().fail(reason, NOW)

    assert failed.status is ExtractionStatus.FAILED
    assert failed.error is not None
    assert (failed.error.reason, failed.error.message) == (reason, FAILURE_MESSAGES[reason])
    assert failed.result is None


def test_every_reason_has_a_message_and_the_terminal_ones_are_those_a_retry_cannot_cure() -> None:
    assert set(FAILURE_MESSAGES) == set(FailureReason)
    assert {
        FailureReason.INVALID_FILE,
        FailureReason.TIMED_OUT,
        FailureReason.DOCUMENT_TOO_LONG,
        FailureReason.INTERRUPTED,
    } == TERMINAL_REASONS


def test_a_retry_goes_back_to_pending_and_keeps_the_attempt_used() -> None:
    again = running().retry()

    assert (again.status, again.attempts, again.started_at) == (ExtractionStatus.PENDING, 1, None)


def test_a_busy_parser_gives_the_attempt_back() -> None:
    again = running().requeue_busy()

    assert (again.status, again.attempts, again.started_at) == (ExtractionStatus.PENDING, 0, None)


def test_an_interrupted_job_runs_again_while_an_attempt_is_left() -> None:
    again = running().interrupted(max_attempts=2, now=NOW)

    assert (again.status, again.attempts, again.error) == (ExtractionStatus.PENDING, 1, None)


def test_an_interrupted_job_with_no_attempt_left_fails_as_interrupted() -> None:
    ended = ExtractionFactory.build(attempts=1).claim(NOW).interrupted(max_attempts=2, now=NOW + timedelta(seconds=1))

    assert ended.status is ExtractionStatus.FAILED
    assert ended.error is not None
    assert ended.error.reason is FailureReason.INTERRUPTED
    assert ended.finished_at == NOW + timedelta(seconds=1)


type Move = Callable[[Extraction], Extraction]

MOVES: dict[str, Move] = {
    "claim": lambda e: e.claim(NOW),
    "complete": lambda e: e.complete({}, NOW),
    "fail": lambda e: e.fail(FailureReason.TIMED_OUT, NOW),
    "retry": lambda e: e.retry(),
    "requeue_busy": lambda e: e.requeue_busy(),
    "interrupted": lambda e: e.interrupted(2, NOW),
}


@pytest.mark.parametrize("name", [n for n in MOVES if n != "claim"])
def test_a_pending_extraction_can_only_be_claimed(name: str) -> None:
    with pytest.raises(InvalidTransition, match="pending"):
        MOVES[name](ExtractionFactory.build())


def test_a_running_extraction_cannot_be_claimed_again() -> None:
    with pytest.raises(InvalidTransition, match="running"):
        running().claim(NOW)


@pytest.mark.parametrize("name", list(MOVES))
@pytest.mark.parametrize("end", ["completed", "failed"])
def test_a_finished_extraction_refuses_every_move(name: str, end: str) -> None:
    finished = running().complete({}, NOW) if end == "completed" else running().fail(FailureReason.TIMED_OUT, NOW)

    with pytest.raises(InvalidTransition, match=end):
        MOVES[name](finished)


def test_an_extraction_expires_a_time_to_live_after_it_finished_and_never_before() -> None:
    ttl = timedelta(hours=24)
    done = running().complete({}, NOW)

    assert not done.is_expired(NOW + ttl - timedelta(seconds=1), ttl)
    assert done.is_expired(NOW + ttl, ttl)


def test_a_job_that_has_not_finished_never_expires() -> None:
    ttl = timedelta(hours=1)

    assert not ExtractionFactory.build().is_expired(NOW + timedelta(days=30), ttl)
    assert not running().is_expired(NOW + timedelta(days=30), ttl)


def test_missing_required_names_the_required_fields_that_came_back_null_in_template_order() -> None:
    template = TemplateSnapshotFactory.build(
        fields=(
            SnapshotFieldFactory.build(name="a", required=True),
            SnapshotFieldFactory.build(name="b", required=False),
            SnapshotFieldFactory.build(name="c", required=True),
            SnapshotFieldFactory.build(name="d", required=True),
        )
    )
    done = (
        ExtractionFactory.build(template=template).claim(NOW).complete({"a": None, "b": None, "c": "x", "d": None}, NOW)
    )

    assert done.missing_required == ["a", "d"]


def test_a_value_that_is_falsy_but_not_null_is_not_missing() -> None:
    template = TemplateSnapshotFactory.build(
        fields=(SnapshotFieldFactory.build(name="count", type="integer", required=True),)
    )
    done = ExtractionFactory.build(template=template).claim(NOW).complete({"count": 0}, NOW)

    assert done.missing_required == []


def test_an_extraction_that_has_no_result_has_nothing_missing() -> None:
    assert ExtractionFactory.build().missing_required == []
    assert running().fail(FailureReason.TIMED_OUT, NOW).missing_required == []
