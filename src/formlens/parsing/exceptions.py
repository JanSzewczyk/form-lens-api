"""Domain errors of document parsing. They carry fixed text and know nothing of HTTP."""

from typing import Final

# One page took 1.2 to 1.8 s on an M1 Pro with `mlx`; a longer document or the slower `transformers`
# backend keeps the slot longer, so the wait stays a constant 5 seconds (README, "How long a page takes").
RETRY_AFTER_SECONDS: Final = 5


class InvalidFile(Exception):
    """The file is empty, or its signature is known but Docling cannot read it."""

    def __init__(self, reason: str = "The file is not a readable document.") -> None:
        """Keep a fixed reason; it is shown to the client, so it never holds Docling's text."""
        super().__init__(reason)


class FileTooLarge(Exception):
    """The upload is larger than `MAX_UPLOAD_MB`."""

    def __init__(self, max_mb: int) -> None:
        """Name the limit, which comes from the settings and not from the client."""
        super().__init__(f"The file is larger than the {max_mb} MB limit.")


class UnsupportedMediaType(Exception):
    """The content is not a PDF, PNG, JPEG or TIFF."""

    def __init__(self) -> None:
        """State what is accepted."""
        super().__init__("Send a PDF, PNG, JPEG or TIFF file.")


class ParseFailed(Exception):
    """The document model failed, timed out or returned an incomplete result."""

    def __init__(self, conversion_status: str | None = None) -> None:
        """Say nothing of the cause: it is in the server log, not in the answer.

        `conversion_status` is Docling's status value (`failure`, `partial_success` for a timeout or an
        incomplete result, ...) when the conversion ended without raising. It is an enum value and never
        document content, so the log may carry it.
        """
        self.conversion_status = conversion_status
        super().__init__("The document could not be parsed.")


class ParserBusy(Exception):
    """Every parsing slot is taken; the client should try again."""

    def __init__(self, retry_after_seconds: int = RETRY_AFTER_SECONDS) -> None:
        """Carry the wait the `Retry-After` header repeats."""
        self.retry_after_seconds = retry_after_seconds
        super().__init__("The parser is busy with other documents. Try again shortly.")


class ModelUnavailable(Exception):
    """The document model is not loaded, so no document can be parsed."""

    def __init__(self, reason: str = "The document model is not available.") -> None:
        """Say only that the model is not ready; a startup failure may say which files are missing.

        A request never carries a custom reason: it reaches the log of the failed startup, not a client.
        """
        super().__init__(reason)
