"""Run a job on its own thread and stop waiting for it after a time."""

import threading
from collections.abc import Callable

from formlens.extractions.domain.exceptions import DeadlineExceeded


class ThreadDeadline:
    """Runs each job on a daemon thread.

    A thread cannot be stopped, so a job that ran out of time is abandoned, not killed. `busy` says it is still
    alive, which is what the worker needs to know before it starts another. The thread is a daemon, so a job
    that never ends does not hold the process open at shutdown.
    """

    def __init__(self) -> None:
        """Start with nothing abandoned."""
        self._abandoned: threading.Thread | None = None
        self._lock = threading.Lock()

    def run[T](self, job: Callable[[], T], timeout_seconds: float) -> T:
        """Return what `job` returns or raise what it raises; give up waiting after `timeout_seconds`."""
        outcome: list[T] = []
        failure: list[BaseException] = []

        def target() -> None:
            try:
                outcome.append(job())
            except BaseException as exc:  # noqa: BLE001 - handed to the waiting caller, who decides
                failure.append(exc)

        thread = threading.Thread(target=target, name="extraction-job", daemon=True)
        thread.start()
        thread.join(timeout_seconds)
        if thread.is_alive():
            with self._lock:
                self._abandoned = thread
            raise DeadlineExceeded
        if failure:
            raise failure[0]
        return outcome[0]

    def busy(self) -> bool:
        """Tell whether a job that was given up on is still running."""
        with self._lock:
            if self._abandoned is not None and not self._abandoned.is_alive():
                self._abandoned = None
            return self._abandoned is not None
