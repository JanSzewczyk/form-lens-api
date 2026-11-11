"""The extraction and its life: pending, running, then completed or failed.

Each transition returns a new frozen object and refuses a move the state does not allow, so a rule such as
"a job that timed out cannot complete" is written once, here, and the repository only has to make the same
move atomic in storage. Standard library only.
"""

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any
from uuid import UUID

from formlens.extractions.domain.exceptions import InvalidTransition


class ExtractionStatus(StrEnum):
    """Where an extraction is in its life."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class FailureReason(StrEnum):
    """Why an extraction failed."""

    INVALID_FILE = "invalid_file"
    PARSE_FAILED = "parse_failed"
    LLM_UNAVAILABLE = "llm_unavailable"
    INVALID_OUTPUT = "invalid_output"
    TIMED_OUT = "timed_out"
    INTERRUPTED = "interrupted"
    DOCUMENT_TOO_LONG = "document_too_long"


# What a client reads. Fixed text: a library's message can quote the document.
FAILURE_MESSAGES: dict[FailureReason, str] = {
    FailureReason.INVALID_FILE: "The document could not be read.",
    FailureReason.PARSE_FAILED: "The text could not be read from the document.",
    FailureReason.LLM_UNAVAILABLE: "The language model could not be reached.",
    FailureReason.INVALID_OUTPUT: "The language model did not return a result that fits the template.",
    FailureReason.TIMED_OUT: "The extraction took longer than the time allowed.",
    FailureReason.INTERRUPTED: "The service stopped before the extraction finished.",
    FailureReason.DOCUMENT_TOO_LONG: "The document is longer than the model can be given.",
}

# D8: these end the job at once, because a second try gives the same answer. The others are retried while
# attempts remain.
TERMINAL_REASONS: frozenset[FailureReason] = frozenset(
    {FailureReason.INVALID_FILE, FailureReason.TIMED_OUT, FailureReason.DOCUMENT_TOO_LONG, FailureReason.INTERRUPTED}
)


@dataclass(frozen=True, slots=True)
class ExtractionError:
    """How an extraction failed: a reason and the fixed text that goes with it."""

    reason: FailureReason
    message: str


@dataclass(frozen=True, slots=True)
class SnapshotField:
    """One field of the template as it was when the extraction was submitted."""

    name: str
    type: str
    description: str
    required: bool


@dataclass(frozen=True, slots=True)
class TemplateSnapshot:
    """A copy of the template taken at submit time, so later edits or a delete never change a queued job."""

    template_id: UUID
    version: int
    name: str
    fields: tuple[SnapshotField, ...]
    json_schema: dict[str, Any]


@dataclass(frozen=True, slots=True)
class Extraction:
    """One document read against one template.

    `attempts` counts the times a worker took the job, at the moment it took it. `result` holds one key per
    field of the template, `null` where the form shows nothing.
    """

    id: UUID
    template: TemplateSnapshot
    status: ExtractionStatus
    attempts: int
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    result: dict[str, Any] | None = None
    error: ExtractionError | None = None

    @classmethod
    def new(cls, extraction_id: UUID, template: TemplateSnapshot, now: datetime) -> Extraction:
        """Return a job that waits for a worker."""
        return cls(id=extraction_id, template=template, status=ExtractionStatus.PENDING, attempts=0, created_at=now)

    def _require(self, status: ExtractionStatus, move: str) -> None:
        if self.status is not status:
            msg = f"cannot {move} an extraction that is {self.status.value}"
            raise InvalidTransition(msg)

    @property
    def is_finished(self) -> bool:
        """Tell whether the extraction reached an end: completed or failed."""
        return self.status in {ExtractionStatus.COMPLETED, ExtractionStatus.FAILED}

    def claim(self, now: datetime) -> Extraction:
        """A worker takes the job; the attempt is counted now, so a crash in the middle still uses it up."""
        self._require(ExtractionStatus.PENDING, "claim")
        return replace(self, status=ExtractionStatus.RUNNING, attempts=self.attempts + 1, started_at=now)

    def complete(self, result: dict[str, Any], now: datetime) -> Extraction:
        """The job produced a result."""
        self._require(ExtractionStatus.RUNNING, "complete")
        return replace(self, status=ExtractionStatus.COMPLETED, finished_at=now, result=result)

    def fail(self, reason: FailureReason, now: datetime) -> Extraction:
        """The job ended without a result."""
        self._require(ExtractionStatus.RUNNING, "fail")
        error = ExtractionError(reason, FAILURE_MESSAGES[reason])
        return replace(self, status=ExtractionStatus.FAILED, finished_at=now, error=error)

    def retry(self) -> Extraction:
        """The attempt failed in a way a second try may cure: back to the queue, the attempt stays used."""
        self._require(ExtractionStatus.RUNNING, "retry")
        return replace(self, status=ExtractionStatus.PENDING, started_at=None)

    def requeue_busy(self) -> Extraction:
        """The parser had no free slot: back to the queue, and the attempt is given back."""
        self._require(ExtractionStatus.RUNNING, "requeue")
        return replace(self, status=ExtractionStatus.PENDING, attempts=self.attempts - 1, started_at=None)

    def interrupted(self, max_attempts: int, now: datetime) -> Extraction:
        """The service stopped while this job ran: run it again if an attempt is left, else fail it."""
        self._require(ExtractionStatus.RUNNING, "recover")
        if self.attempts < max_attempts:
            return replace(self, status=ExtractionStatus.PENDING, started_at=None)
        return self.fail(FailureReason.INTERRUPTED, now)

    def is_expired(self, now: datetime, ttl: timedelta) -> bool:
        """Tell whether a finished extraction is older than its time to live; one that is not finished never is."""
        return self.finished_at is not None and now >= self.finished_at + ttl

    @property
    def missing_required(self) -> list[str]:
        """Name the required fields whose value is `null` in a completed result, in template order."""
        if self.result is None:
            return []
        return [item.name for item in self.template.fields if item.required and self.result.get(item.name) is None]


@dataclass(frozen=True, slots=True)
class RecoveryCounts:
    """What a recovery did: jobs that go back to the queue and jobs that ended as `interrupted`."""

    requeued: int
    failed: int
