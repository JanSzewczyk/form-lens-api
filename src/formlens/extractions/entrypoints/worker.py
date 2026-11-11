"""The background worker: one asyncio task that runs one job at a time on a thread."""

import asyncio
import contextlib
import time

import structlog
from anyio import to_thread

from formlens.extractions.service_layer.processor import ExtractionProcessor

log = structlog.get_logger(__name__)


class ExtractionWorker:
    """Takes jobs from the queue until it is told to stop.

    `ExtractionProcessor.run_once` is synchronous and may block for the whole job time, so it runs on a thread.
    The task never ends on an error: a crash is logged once, by type, and the loop goes on after a pause, so one
    bad job cannot stop the queue and a persistent fault cannot spin.
    """

    def __init__(
        self, processor: ExtractionProcessor, *, poll_interval_seconds: float, purge_interval_seconds: float = 60.0
    ) -> None:
        """Wire the processor and the two intervals."""
        self._processor = processor
        self._poll = poll_interval_seconds
        self._purge_every = purge_interval_seconds
        self._stop = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        """Start the loop on the running event loop."""
        self._stop = asyncio.Event()
        self._task = asyncio.create_task(self._run(), name="extraction-worker")

    async def stop(self, timeout_seconds: float) -> None:
        """Ask the loop to stop and wait for it; a job that is still running after `timeout_seconds` is left behind.

        The thread of such a job cannot be stopped. Its extraction stays `running` and the next start recovers it.
        """
        self._stop.set()
        if self._task is None:
            return
        try:
            await asyncio.wait_for(self._task, timeout_seconds)
        except TimeoutError:
            log.warning("extraction_worker_stop_timed_out", timeout_seconds=timeout_seconds)
        self._task = None

    async def _pause(self) -> None:
        """Wait one poll interval, or less when the worker is told to stop."""
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self._stop.wait(), self._poll)

    async def _guarded(self, step: str) -> bool:
        """Run one step on a thread; True when it did work, False when it had none or crashed (the loop then pauses)."""
        try:
            if step == "job":
                return await to_thread.run_sync(self._processor.run_once, abandon_on_cancel=True)
            await to_thread.run_sync(self._processor.purge_expired, abandon_on_cancel=True)
        except Exception as exc:  # noqa: BLE001 - the loop must survive anything a job or the storage throws
            # Once, here; the type only, because a message can quote a document.
            log.error("extraction_worker_crashed", step=step, cause_type=type(exc).__name__)  # noqa: TRY400
        return False

    async def _run(self) -> None:
        await self._guarded("purge")
        last_purge = time.monotonic()
        while not self._stop.is_set():
            worked = await self._guarded("job")
            if time.monotonic() - last_purge >= self._purge_every:
                await self._guarded("purge")
                last_purge = time.monotonic()
            if not worked and not self._stop.is_set():
                await self._pause()
