"""Domain errors of the extractions; they know nothing of HTTP.

Two families. The first is raised to a caller of `submit` or `get` and becomes an HTTP problem. The second is
raised by a port while a job runs and decides how the job ends; it never reaches a client, the extraction
carries a fixed `error` instead. No message holds document text, a field value or a library's own message.
"""

from uuid import UUID


class ExtractionNotFound(Exception):
    """No extraction has this id, or it has expired."""

    def __init__(self, extraction_id: UUID) -> None:
        """Name the id that was asked for."""
        super().__init__(f"Extraction {extraction_id} does not exist.")
        self.extraction_id = extraction_id


class QueueFull(Exception):
    """The queue holds as many waiting extractions as it may; try again later."""

    def __init__(self, retry_after_seconds: int) -> None:
        """Say how long a client should wait."""
        super().__init__("The queue is full; try again later.")
        self.retry_after_seconds = retry_after_seconds


class TemplateMissing(Exception):
    """The template an extraction asked for does not exist."""

    def __init__(self, template_id: UUID) -> None:
        """Name the id that was asked for."""
        super().__init__(f"Template {template_id} does not exist.")
        self.template_id = template_id


class UploadRefused(Exception):
    """The upload cannot be queued; the subclasses say why."""


class UploadEmpty(UploadRefused):
    """The file is empty."""

    def __init__(self) -> None:
        """Use a fixed message."""
        super().__init__("The file is empty.")


class UploadTooLarge(UploadRefused):
    """The file is larger than the limit."""

    def __init__(self, limit_mb: int) -> None:
        """Name the limit."""
        super().__init__(f"The file is larger than {limit_mb} MB.")
        self.limit_mb = limit_mb


class UploadUnsupported(UploadRefused):
    """The file is not a PDF, PNG, JPEG or TIFF."""

    def __init__(self) -> None:
        """Use a fixed message."""
        super().__init__("The file is not a PDF, PNG, JPEG or TIFF.")


class InvalidTransition(ValueError):
    """An extraction was asked to move to a state it cannot reach from where it is."""


class JobError(Exception):
    """A port failed while a job ran. The subclasses decide whether the job is retried."""


class FileUnreadable(JobError):
    """The document cannot be read at all. Retrying cannot help."""


class ParseFailed(JobError):
    """The text could not be read from the document this time. A retry may work."""


class ParserBusy(JobError):
    """Every parsing slot is taken. The job goes back to the queue and the attempt is given back."""


class LlmUnavailable(JobError):
    """The language model could not be reached or did not answer in time. A retry may work."""


class InvalidOutput(JobError):
    """The language model answered something that does not satisfy the template's schema. A retry may work."""


class DocumentTooLong(JobError):
    """The document text is longer than the model may be given. Retrying cannot help."""


class DeadlineExceeded(Exception):  # a condition, like TimeoutError
    """A job did not finish within its time."""
