"""The thread-based deadline: results, errors, and the memory of a job that was given up on."""

import threading

import pytest

from formlens.extractions.adapters.deadline import ThreadDeadline
from formlens.extractions.domain.exceptions import DeadlineExceeded
from tests.extractions.harness import wait_until


def test_it_returns_what_the_job_returns() -> None:
    deadline = ThreadDeadline()

    assert deadline.run(lambda: 42, 5) == 42
    assert deadline.busy() is False


def fail_with_value_error() -> int:
    raise ValueError("boom")


def test_it_raises_what_the_job_raises() -> None:
    with pytest.raises(ValueError, match="boom"):
        ThreadDeadline().run(fail_with_value_error, 5)


def test_a_job_that_is_too_slow_raises_the_deadline_error_and_stays_busy_until_it_ends() -> None:
    release = threading.Event()
    deadline = ThreadDeadline()

    def slow() -> int:
        release.wait(10)
        return 1

    try:
        with pytest.raises(DeadlineExceeded):
            deadline.run(slow, 0.05)
        assert deadline.busy() is True
    finally:
        release.set()

    assert wait_until(lambda: not deadline.busy())


def test_the_job_runs_on_a_daemon_thread_so_a_job_that_never_ends_cannot_hold_the_process() -> None:
    seen: list[bool] = []

    def look() -> None:
        seen.append(threading.current_thread().daemon)

    ThreadDeadline().run(look, 5)

    assert seen == [True]
