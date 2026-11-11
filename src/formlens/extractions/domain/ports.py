"""What the extraction logic needs from the outside world."""

from collections.abc import Callable
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from formlens.extractions.domain.model import Extraction, RecoveryCounts, TemplateSnapshot


class ExtractionRepository(Protocol):
    """Storage of extractions and of the uploads that wait for a worker.

    Each method is one short transaction. The ones that decide something (claim, finish, enqueue) are atomic in
    storage: two workers or two requests at once cannot both win.
    """

    def add(self, extraction: Extraction, content: bytes, *, max_pending: int) -> None:
        """Store a pending extraction and its upload, unless `max_pending` extractions already wait.

        Raises:
            QueueFull: The queue is at its limit.
        """
        ...

    def get(self, extraction_id: UUID) -> Extraction | None:
        """Return the extraction, or None."""
        ...

    def read_input(self, extraction_id: UUID) -> bytes | None:
        """Return the upload of a job that has not ended, or None."""
        ...

    def claim_next(self, now: datetime) -> Extraction | None:
        """Move the oldest pending extraction to running, count the attempt and return it; None when none waits."""
        ...

    def finish_if_running(self, finished: Extraction) -> bool:
        """Store a completed or failed extraction only if it is still running with the same attempt count.

        Also deletes the upload. Returns False, changing nothing, when the extraction ended or was taken again.
        """
        ...

    def release_if_running(self, released: Extraction, *, claimed_attempts: int) -> bool:
        """Put a running extraction back to pending, only if it is still running with `claimed_attempts`.

        `released` is the result of `retry()` or `requeue_busy()`; its attempt count is the one that is stored.
        Returns False, changing nothing, when the extraction ended or was taken again.
        """
        ...

    def recover_running(self, max_attempts: int, now: datetime) -> RecoveryCounts:
        """After a restart: every running job goes back to pending if an attempt is left, else it fails."""
        ...

    def purge_before(self, cutoff: datetime) -> int:
        """Delete the extractions that finished before `cutoff`; return how many."""
        ...

    def count_pending(self) -> int:
        """Return how many extractions wait."""
        ...


class TextSource(Protocol):
    """Reads the text of a document."""

    def check(self, content: bytes) -> None:
        """Refuse an upload that cannot be read, without reading it.

        Raises:
            UploadEmpty: The file is empty.
            UploadTooLarge: The file is over the limit.
            UploadUnsupported: The file is not a supported document.
        """
        ...

    def extract_text(self, content: bytes) -> str:
        """Return the text of the document.

        Raises:
            FileUnreadable: The document cannot be read.
            ParseFailed: The reader failed.
            ParserBusy: No reader is free.
        """
        ...


class FieldExtractor(Protocol):
    """Reads the fields of a template out of a document's text."""

    def extract(self, text: str, template: TemplateSnapshot) -> dict[str, Any]:
        """Return one value per field of the template, `None` where the text has nothing.

        Raises:
            LlmUnavailable: The model could not be reached or did not answer in time.
            InvalidOutput: The answer does not satisfy the template's schema.
        """
        ...


class TemplateCatalog(Protocol):
    """Where the templates are, seen from the extractions: ids in, plain data out."""

    def snapshot(self, template_id: UUID) -> TemplateSnapshot:
        """Return a copy of the template as it is now.

        Raises:
            TemplateMissing: There is no such template.
        """
        ...


class Deadline(Protocol):
    """Runs one job and gives up waiting for it after a time, without being able to stop it."""

    def run[T](self, job: Callable[[], T], timeout_seconds: float) -> T:
        """Return what `job` returns, or raise what it raises.

        Raises:
            DeadlineExceeded: `job` did not finish in time. It keeps running; `busy` says so.
        """
        ...

    def busy(self) -> bool:
        """Tell whether a job that was given up on is still running."""
        ...
