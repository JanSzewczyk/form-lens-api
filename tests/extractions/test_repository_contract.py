"""One suite, every repository: the fake and the SQLite adapter must behave the same wherever a test relies on it."""

from datetime import timedelta
from uuid import UUID

import pytest

from formlens.extractions.domain.exceptions import QueueFull
from formlens.extractions.domain.model import Extraction, ExtractionStatus, FailureReason
from formlens.extractions.domain.ports import ExtractionRepository
from tests.extractions.factories import NOW, ExtractionFactory

CONTENT = b"%PDF-1.7 content of one upload"
CAP = 100


def add(
    repository: ExtractionRepository, extraction: Extraction, content: bytes = CONTENT, *, cap: int = CAP
) -> Extraction:
    repository.add(extraction, content, max_pending=cap)
    return extraction


def id_of(n: int) -> UUID:
    return UUID(int=n)


def claimed(repository: ExtractionRepository, extraction: Extraction, now_offset: int = 1) -> Extraction:
    add(repository, extraction)
    taken = repository.claim_next(NOW + timedelta(seconds=now_offset))
    assert taken is not None
    assert taken.id == extraction.id
    return taken


# --- add, get, read_input --------------------------------------------------------------------------


def test_an_added_extraction_is_read_back_unchanged_with_its_upload(repository: ExtractionRepository) -> None:
    extraction = add(repository, ExtractionFactory.build(id=id_of(1)))

    assert repository.get(id_of(1)) == extraction
    assert repository.read_input(id_of(1)) == CONTENT


def test_an_unknown_extraction_is_none_and_has_no_upload(repository: ExtractionRepository) -> None:
    assert repository.get(id_of(9)) is None
    assert repository.read_input(id_of(9)) is None


def test_the_snapshot_of_the_template_is_stored_whole(repository: ExtractionRepository) -> None:
    extraction = add(repository, ExtractionFactory.build(id=id_of(1)))

    stored = repository.get(id_of(1))

    assert stored is not None
    assert stored.template == extraction.template
    assert stored.template.json_schema["required"] == ["number", "buyer"]


def test_a_new_extraction_has_no_result_not_a_null_one(repository: ExtractionRepository) -> None:
    add(repository, ExtractionFactory.build(id=id_of(1)))

    stored = repository.get(id_of(1))

    assert stored is not None
    assert (stored.result, stored.error, stored.started_at, stored.finished_at) == (None, None, None, None)


# --- queue cap -------------------------------------------------------------------------------------


def test_the_queue_refuses_the_extraction_after_the_last_free_place_and_keeps_nothing_of_it(
    repository: ExtractionRepository,
) -> None:
    add(repository, ExtractionFactory.build(id=id_of(1)), cap=2)
    add(repository, ExtractionFactory.build(id=id_of(2)), cap=2)

    with pytest.raises(QueueFull) as raised:
        add(repository, ExtractionFactory.build(id=id_of(3)), cap=2)

    assert raised.value.retry_after_seconds > 0
    assert repository.count_pending() == 2
    assert repository.get(id_of(3)) is None
    assert repository.read_input(id_of(3)) is None


def test_only_waiting_extractions_count_against_the_cap(repository: ExtractionRepository) -> None:
    taken = claimed(repository, ExtractionFactory.build(id=id_of(1)))
    add(repository, ExtractionFactory.build(id=id_of(2)), cap=1)  # the running one does not count

    with pytest.raises(QueueFull):
        add(repository, ExtractionFactory.build(id=id_of(3)), cap=1)
    repository.finish_if_running(taken.complete({}, NOW))

    assert repository.count_pending() == 1


# --- claim -----------------------------------------------------------------------------------------


def test_claiming_takes_the_oldest_waiting_extraction_and_counts_the_attempt(repository: ExtractionRepository) -> None:
    add(repository, ExtractionFactory.build(id=id_of(2), created_at=NOW + timedelta(seconds=5)))
    add(repository, ExtractionFactory.build(id=id_of(1), created_at=NOW))
    taken_at = NOW + timedelta(seconds=30)

    taken = repository.claim_next(taken_at)

    assert taken is not None
    assert (taken.id, taken.status, taken.attempts, taken.started_at) == (
        id_of(1),
        ExtractionStatus.RUNNING,
        1,
        taken_at,
    )
    assert repository.get(id_of(1)) == taken
    assert repository.count_pending() == 1


def test_two_extractions_created_at_the_same_time_are_claimed_in_id_order(repository: ExtractionRepository) -> None:
    add(repository, ExtractionFactory.build(id=id_of(7)))
    add(repository, ExtractionFactory.build(id=id_of(3)))

    first, second = repository.claim_next(NOW), repository.claim_next(NOW)

    assert first is not None
    assert second is not None
    assert (first.id, second.id) == (id_of(3), id_of(7))


def test_claiming_with_nothing_waiting_is_none_and_a_running_one_is_not_claimed_again(
    repository: ExtractionRepository,
) -> None:
    assert repository.claim_next(NOW) is None
    claimed(repository, ExtractionFactory.build(id=id_of(1)))

    assert repository.claim_next(NOW) is None


def test_the_claimed_extraction_still_has_its_upload(repository: ExtractionRepository) -> None:
    claimed(repository, ExtractionFactory.build(id=id_of(1)))

    assert repository.read_input(id_of(1)) == CONTENT


# --- finish ----------------------------------------------------------------------------------------


def test_finishing_a_running_extraction_stores_the_result_and_deletes_the_upload(
    repository: ExtractionRepository,
) -> None:
    taken = claimed(repository, ExtractionFactory.build(id=id_of(1)))
    done = taken.complete({"number": "42", "buyer": None}, NOW + timedelta(seconds=9))

    assert repository.finish_if_running(done) is True

    assert repository.get(id_of(1)) == done
    assert repository.read_input(id_of(1)) is None


def test_a_failure_is_stored_with_its_reason_and_fixed_message(repository: ExtractionRepository) -> None:
    taken = claimed(repository, ExtractionFactory.build(id=id_of(1)))
    failed = taken.fail(FailureReason.INVALID_OUTPUT, NOW + timedelta(seconds=9))

    assert repository.finish_if_running(failed) is True

    stored = repository.get(id_of(1))
    assert stored == failed
    assert stored is not None
    assert stored.error is not None
    assert stored.error.reason is FailureReason.INVALID_OUTPUT
    assert repository.read_input(id_of(1)) is None


def test_a_result_arriving_after_a_timeout_changes_nothing(repository: ExtractionRepository) -> None:
    taken = claimed(repository, ExtractionFactory.build(id=id_of(1)))
    timed_out = taken.fail(FailureReason.TIMED_OUT, NOW + timedelta(seconds=600))
    late = taken.complete({"number": "42", "buyer": None}, NOW + timedelta(seconds=700))
    assert repository.finish_if_running(timed_out) is True

    assert repository.finish_if_running(late) is False

    assert repository.get(id_of(1)) == timed_out


def test_a_second_finish_of_the_same_attempt_changes_nothing(repository: ExtractionRepository) -> None:
    taken = claimed(repository, ExtractionFactory.build(id=id_of(1)))
    first = taken.complete({"number": "1", "buyer": None}, NOW)
    assert repository.finish_if_running(first) is True

    assert repository.finish_if_running(taken.complete({"number": "2", "buyer": None}, NOW)) is False

    assert repository.get(id_of(1)) == first


def test_a_result_of_an_earlier_attempt_does_not_end_the_later_one(repository: ExtractionRepository) -> None:
    first_attempt = claimed(repository, ExtractionFactory.build(id=id_of(1)))
    assert repository.release_if_running(first_attempt.retry(), claimed_attempts=1) is True
    second_attempt = repository.claim_next(NOW + timedelta(seconds=5))
    assert second_attempt is not None
    assert second_attempt.attempts == 2

    assert repository.finish_if_running(first_attempt.complete({"number": "old", "buyer": None}, NOW)) is False

    assert repository.get(id_of(1)) == second_attempt


def test_finishing_an_unknown_extraction_is_false(repository: ExtractionRepository) -> None:
    ghost = ExtractionFactory.build(id=id_of(5)).claim(NOW).complete({}, NOW)

    assert repository.finish_if_running(ghost) is False


# --- release ---------------------------------------------------------------------------------------


def test_a_retry_goes_back_to_the_queue_keeps_its_attempt_and_its_upload(repository: ExtractionRepository) -> None:
    taken = claimed(repository, ExtractionFactory.build(id=id_of(1)))

    assert repository.release_if_running(taken.retry(), claimed_attempts=1) is True

    stored = repository.get(id_of(1))
    assert stored is not None
    assert (stored.status, stored.attempts, stored.started_at) == (ExtractionStatus.PENDING, 1, None)
    assert repository.read_input(id_of(1)) == CONTENT
    again = repository.claim_next(NOW)
    assert again is not None
    assert again.attempts == 2


def test_a_busy_parser_gives_the_attempt_back(repository: ExtractionRepository) -> None:
    taken = claimed(repository, ExtractionFactory.build(id=id_of(1)))

    assert repository.release_if_running(taken.requeue_busy(), claimed_attempts=1) is True

    stored = repository.get(id_of(1))
    assert stored is not None
    assert (stored.status, stored.attempts) == (ExtractionStatus.PENDING, 0)
    again = repository.claim_next(NOW)
    assert again is not None
    assert again.attempts == 1


def test_releasing_an_extraction_that_already_ended_or_was_taken_again_changes_nothing(
    repository: ExtractionRepository,
) -> None:
    taken = claimed(repository, ExtractionFactory.build(id=id_of(1)))
    timed_out = taken.fail(FailureReason.TIMED_OUT, NOW)
    assert repository.finish_if_running(timed_out) is True

    assert repository.release_if_running(taken.requeue_busy(), claimed_attempts=1) is False
    assert repository.get(id_of(1)) == timed_out


def test_a_release_by_an_earlier_attempt_does_not_put_the_later_attempt_back_in_the_queue(
    repository: ExtractionRepository,
) -> None:
    """The guard of the attempt count in `release_if_running`: only the attempt that holds the job may give it back."""
    first = claimed(repository, ExtractionFactory.build(id=id_of(1)))
    assert repository.release_if_running(first.retry(), claimed_attempts=1) is True
    second = repository.claim_next(NOW + timedelta(seconds=5))
    assert second is not None
    assert second.attempts == 2

    stale = repository.release_if_running(first.requeue_busy(), claimed_attempts=1)

    assert stale is False
    assert repository.get(id_of(1)) == second
    assert repository.count_pending() == 0


# --- recovery --------------------------------------------------------------------------------------


def test_recovery_requeues_a_running_job_with_an_attempt_left_and_fails_one_without(
    repository: ExtractionRepository,
) -> None:
    add(repository, ExtractionFactory.build(id=id_of(1), created_at=NOW))
    add(repository, ExtractionFactory.build(id=id_of(2), created_at=NOW + timedelta(seconds=1)))
    repository.claim_next(NOW)  # id 1, attempt 1
    second = repository.claim_next(NOW)  # id 2, attempt 1
    assert second is not None
    assert repository.release_if_running(second.retry(), claimed_attempts=1) is True
    assert repository.claim_next(NOW) is not None  # id 2, attempt 2
    restart = NOW + timedelta(minutes=5)

    counts = repository.recover_running(2, restart)

    assert (counts.requeued, counts.failed) == (1, 1)
    one, two = repository.get(id_of(1)), repository.get(id_of(2))
    assert one is not None
    assert two is not None
    assert (one.status, one.attempts, one.started_at) == (ExtractionStatus.PENDING, 1, None)
    assert two.status is ExtractionStatus.FAILED
    assert two.error is not None
    assert two.error.reason is FailureReason.INTERRUPTED
    assert two.finished_at == restart
    assert repository.read_input(id_of(1)) == CONTENT
    assert repository.read_input(id_of(2)) is None


def test_recovery_leaves_waiting_and_finished_extractions_alone(repository: ExtractionRepository) -> None:
    add(repository, ExtractionFactory.build(id=id_of(1), created_at=NOW))
    add(repository, ExtractionFactory.build(id=id_of(2), created_at=NOW + timedelta(seconds=1)))
    done = repository.claim_next(NOW)
    assert done is not None
    finished = done.complete({"number": "1", "buyer": None}, NOW)
    repository.finish_if_running(finished)

    counts = repository.recover_running(2, NOW)

    assert (counts.requeued, counts.failed) == (0, 0)
    assert repository.get(id_of(1)) == finished
    waiting = repository.get(id_of(2))
    assert waiting is not None
    assert waiting.status is ExtractionStatus.PENDING


# --- purge -----------------------------------------------------------------------------------------


def test_purge_deletes_what_finished_before_the_cutoff_and_nothing_else(repository: ExtractionRepository) -> None:
    old = claimed(repository, ExtractionFactory.build(id=id_of(1), created_at=NOW), 1)
    repository.finish_if_running(old.complete({"number": "1", "buyer": None}, NOW + timedelta(hours=1)))
    recent = claimed(repository, ExtractionFactory.build(id=id_of(2), created_at=NOW + timedelta(seconds=1)), 2)
    repository.finish_if_running(recent.complete({"number": "2", "buyer": None}, NOW + timedelta(hours=30)))
    running_one = claimed(repository, ExtractionFactory.build(id=id_of(4), created_at=NOW + timedelta(seconds=3)), 3)
    add(repository, ExtractionFactory.build(id=id_of(3), created_at=NOW + timedelta(seconds=2)))

    purged = repository.purge_before(NOW + timedelta(hours=25))

    assert purged == 1
    assert repository.get(id_of(1)) is None
    assert repository.get(id_of(2)) is not None
    assert repository.get(id_of(3)) is not None
    assert repository.get(id_of(4)) == running_one
    assert repository.read_input(id_of(4)) == CONTENT


def test_purging_twice_deletes_nothing_the_second_time(repository: ExtractionRepository) -> None:
    taken = claimed(repository, ExtractionFactory.build(id=id_of(1)))
    repository.finish_if_running(taken.complete({}, NOW))

    assert repository.purge_before(NOW + timedelta(days=1)) == 1
    assert repository.purge_before(NOW + timedelta(days=1)) == 0


def test_a_job_finishing_exactly_at_the_cutoff_is_kept(repository: ExtractionRepository) -> None:
    taken = claimed(repository, ExtractionFactory.build(id=id_of(1)))
    repository.finish_if_running(taken.complete({}, NOW + timedelta(hours=1)))

    assert repository.purge_before(NOW + timedelta(hours=1)) == 0


def test_an_upload_of_any_bytes_is_stored_and_read_back_exactly(repository: ExtractionRepository) -> None:
    content = bytes(range(256)) * 100
    add(repository, ExtractionFactory.build(id=id_of(1)), content)

    assert repository.read_input(id_of(1)) == content
