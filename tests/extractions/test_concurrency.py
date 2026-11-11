"""The atomic guards of the queue, proved on a real SQLite file with competing threads.

An in-memory database or one connection would prove nothing: the guards only matter when connections really
compete. Each test releases the competing calls together from a barrier and asserts on the final state.
"""

import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import UUID

import pytest

from formlens.database import Database
from formlens.extractions.adapters.sqlite_repository import SqliteExtractionRepository
from formlens.extractions.domain.exceptions import QueueFull
from formlens.extractions.domain.model import Extraction, ExtractionStatus, FailureReason
from tests.extractions.factories import NOW, ExtractionFactory

CONTENT = b"%PDF-1.7 upload"
THREADS = 6


def ids(n: int) -> list[UUID]:
    return [UUID(int=i + 1) for i in range(n)]


@pytest.mark.concurrency
def test_every_waiting_job_is_claimed_exactly_once_by_competing_workers(database: Database) -> None:
    repository = SqliteExtractionRepository(database)
    jobs = ids(12)
    for i, job_id in enumerate(jobs):
        repository.add(
            ExtractionFactory.build(id=job_id, created_at=NOW + timedelta(seconds=i)), CONTENT, max_pending=100
        )
    barrier = threading.Barrier(THREADS, timeout=5)  # a timeout fails a stuck run fast

    def work(_: int) -> list[tuple[UUID, int]]:
        barrier.wait()
        taken: list[tuple[UUID, int]] = []
        while (job := repository.claim_next(NOW + timedelta(hours=1))) is not None:
            taken.append((job.id, job.attempts))
        return taken

    with ThreadPoolExecutor(THREADS) as pool:  # pool size >= Barrier parties
        claimed = [item for taken in pool.map(work, range(THREADS)) for item in taken]

    assert sorted(job_id for job_id, _ in claimed) == jobs  # no job twice, none lost
    assert {attempts for _, attempts in claimed} == {1}
    assert repository.count_pending() == 0
    stored = [repository.get(job_id) for job_id in jobs]
    assert all(row is not None and row.status is ExtractionStatus.RUNNING and row.attempts == 1 for row in stored)


@pytest.mark.concurrency
def test_a_timeout_and_a_late_result_at_the_same_moment_leave_exactly_one_of_them_written(database: Database) -> None:
    repository = SqliteExtractionRepository(database)
    job_id = ids(1)[0]
    repository.add(ExtractionFactory.build(id=job_id), CONTENT, max_pending=100)
    claimed = repository.claim_next(NOW)
    assert claimed is not None
    late_result = claimed.complete({"number": "42", "buyer": None}, NOW + timedelta(seconds=700))
    timed_out = claimed.fail(FailureReason.TIMED_OUT, NOW + timedelta(seconds=600))
    barrier = threading.Barrier(2, timeout=5)

    def write(finished: Extraction) -> bool:
        barrier.wait()
        return repository.finish_if_running(finished)

    with ThreadPoolExecutor(2) as pool:
        outcomes = list(pool.map(write, [late_result, timed_out]))

    stored = repository.get(job_id)
    assert sorted(outcomes) == [False, True]
    assert stored in (late_result, timed_out)  # whole: never a mix of the two
    winner = late_result if outcomes[0] else timed_out
    assert stored == winner


@pytest.mark.concurrency
def test_only_as_many_parallel_submissions_as_the_queue_has_room_for_are_accepted(database: Database) -> None:
    repository = SqliteExtractionRepository(database)
    room = 3
    jobs = ids(8)
    barrier = threading.Barrier(len(jobs), timeout=5)

    def submit(job_id: UUID) -> bool:
        barrier.wait()
        try:
            repository.add(ExtractionFactory.build(id=job_id), CONTENT, max_pending=room)
        except QueueFull:
            return False
        return True

    with ThreadPoolExecutor(len(jobs)) as pool:
        accepted = list(pool.map(submit, jobs))

    assert Counter(accepted) == {True: room, False: len(jobs) - room}
    assert repository.count_pending() == room
    stored = [job_id for job_id in jobs if repository.get(job_id) is not None]
    assert len(stored) == room
    assert all(repository.read_input(job_id) == CONTENT for job_id in stored)  # an accepted job has its upload
    assert all(repository.read_input(job_id) is None for job_id in jobs if job_id not in stored)
