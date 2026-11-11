"""The worker's one step: take a job, run it within its time, write how it ended.

`run_once` is synchronous and does one job, so a test drives it directly. The loop that calls it (and the
threads) live in the entrypoint.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

import structlog

from formlens.extractions.domain.exceptions import (
    DeadlineExceeded,
    DocumentTooLong,
    FileUnreadable,
    InvalidOutput,
    LlmUnavailable,
    ParseFailed,
    ParserBusy,
)
from formlens.extractions.domain.model import TERMINAL_REASONS, Extraction, FailureReason
from formlens.extractions.domain.ports import Deadline, ExtractionRepository, FieldExtractor, TextSource
from formlens.extractions.service_layer.service import utc_now

log = structlog.get_logger(__name__)

# A cause that is not worth a second try maps to a terminal reason; the others are retried (D8).
_REASONS: tuple[tuple[type[Exception], FailureReason], ...] = (
    (FileUnreadable, FailureReason.INVALID_FILE),
    (DocumentTooLong, FailureReason.DOCUMENT_TOO_LONG),
    (ParseFailed, FailureReason.PARSE_FAILED),
    (LlmUnavailable, FailureReason.LLM_UNAVAILABLE),
    (InvalidOutput, FailureReason.INVALID_OUTPUT),
)


@dataclass(frozen=True, slots=True)
class ProcessorConfig:
    """The limits of the worker."""

    max_attempts: int
    job_timeout_seconds: float
    result_ttl: timedelta
    max_input_chars: int


class ExtractionProcessor:
    """Runs queued extractions one at a time."""

    def __init__(  # the ports and the config are the dependencies
        self,
        repository: ExtractionRepository,
        text_source: TextSource,
        extractor: FieldExtractor,
        deadline: Deadline,
        config: ProcessorConfig,
        *,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        """Wire the ports and the limits."""
        self._repository = repository
        self._text_source = text_source
        self._extractor = extractor
        self._deadline = deadline
        self._config = config
        self._clock = clock

    def run_once(self) -> bool:
        """Do one job if one waits; return whether a job was taken.

        Nothing is taken while a job that ran out of time is still running: Python cannot stop it, it still
        holds a parser slot and memory, and a second job beside it would break the concurrency limit.
        """
        if self._deadline.busy():
            return False
        claimed = self._repository.claim_next(self._clock())
        if claimed is None:
            return False
        log.info("extraction_claimed", extraction_id=str(claimed.id), attempt=claimed.attempts)
        content = self._repository.read_input(claimed.id)
        if content is None:
            self._finish(claimed.fail(FailureReason.INTERRUPTED, self._clock()), claimed)
            return True
        try:
            result = self._deadline.run(lambda: self._work(claimed, content), self._config.job_timeout_seconds)
        except DeadlineExceeded:
            self._finish(claimed.fail(FailureReason.TIMED_OUT, self._clock()), claimed)
        except ParserBusy:
            # No slot is free: this was not an attempt, so the job goes back and the attempt is given back.
            self._repository.release_if_running(claimed.requeue_busy(), claimed_attempts=claimed.attempts)
        except Exception as exc:  # noqa: BLE001 - a port is trusted to translate; an unknown error ends the job
            self._after_failure(claimed, self._reason_of(exc), cause=type(exc).__name__)
        else:
            self._finish(claimed.complete(result, self._clock()), claimed)
        return True

    def _work(self, claimed: Extraction, content: bytes) -> dict[str, object]:
        """The part that runs under the deadline, on another thread."""
        text = self._text_source.extract_text(content)
        if len(text) > self._config.max_input_chars:
            raise DocumentTooLong
        return self._extractor.extract(text, claimed.template)

    @staticmethod
    def _reason_of(exc: Exception) -> FailureReason:
        for kind, reason in _REASONS:
            if isinstance(exc, kind):
                return reason
        return FailureReason.INTERRUPTED  # an error nobody translated: the job did not complete

    def _after_failure(self, claimed: Extraction, reason: FailureReason, *, cause: str) -> None:
        """End the job, or give it another go while it has attempts left and a second try can help."""
        if reason not in TERMINAL_REASONS and claimed.attempts < self._config.max_attempts:
            self._repository.release_if_running(claimed.retry(), claimed_attempts=claimed.attempts)
            log.info("extraction_retry", extraction_id=str(claimed.id), reason=reason.value, cause_type=cause)
            return
        self._finish(claimed.fail(reason, self._clock()), claimed, cause_type=cause)

    def _finish(self, finished: Extraction, claimed: Extraction, **fields: object) -> None:
        """Write the end of the job if this attempt still owns it; a late writer changes nothing."""
        stored = self._repository.finish_if_running(finished)
        elapsed_ms = (
            round((finished.finished_at - claimed.started_at).total_seconds() * 1000)
            if (finished.finished_at and claimed.started_at)
            else None
        )
        log.info(
            "extraction_finished",
            extraction_id=str(claimed.id),
            status=finished.status.value,
            reason=finished.error.reason.value if finished.error else None,
            attempt=claimed.attempts,
            elapsed_ms=elapsed_ms,
            applied=stored,
            **fields,
        )

    def recover(self) -> None:
        """Run once at start, before the worker: jobs a stopped service left running go on or end."""
        counts = self._repository.recover_running(self._config.max_attempts, self._clock())
        if counts.requeued or counts.failed:
            log.warning("extraction_recovered", requeued=counts.requeued, failed=counts.failed)

    def purge_expired(self) -> int:
        """Delete finished extractions past their time to live; return how many."""
        purged = self._repository.purge_before(self._clock() - self._config.result_ttl)
        if purged:
            log.info("extractions_purged", count=purged)
        return purged
