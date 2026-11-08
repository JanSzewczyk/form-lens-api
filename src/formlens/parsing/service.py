"""The parsing use case: refuse what cannot be parsed, hold a slot, call the parser."""

import structlog

from formlens.parsing.exceptions import (
    FileTooLarge,
    InvalidFile,
    ModelUnavailable,
    ParseFailed,
    ParserBusy,
    UnsupportedMediaType,
)
from formlens.parsing.models import BYTES_PER_MB, OutputFormat, ParsedDocument, detect_document_type
from formlens.parsing.ports import DocumentParser, ParseResult
from formlens.parsing.slots import ParseSlots

log = structlog.get_logger(__name__)


class DocumentService:
    """Parses one upload. The order of the checks is the order of their cost."""

    def __init__(self, parser: DocumentParser, slots: ParseSlots, *, max_upload_mb: int) -> None:
        """Wire the parser, the slots and the size limit."""
        self._parser = parser
        self._slots = slots
        self._max_upload_mb = max_upload_mb

    def parse(self, content: bytes, output_format: OutputFormat) -> ParsedDocument:
        """Return the text of `content` in `output_format`.

        Raises:
            InvalidFile: The content is empty, or the parser cannot read it.
            FileTooLarge: The content is larger than the limit.
            UnsupportedMediaType: The content is not a PDF, PNG, JPEG or TIFF.
            ParserBusy: Every slot is taken.
            ParseFailed: The parser failed.
        """
        if not content:
            raise InvalidFile("The file is empty.")
        if len(content) > self._max_upload_mb * BYTES_PER_MB:
            raise FileTooLarge(self._max_upload_mb)
        kind = detect_document_type(content)
        if kind is None:
            raise UnsupportedMediaType
        try:
            with self._slots.hold():
                result = self._parse(content, kind.extension)
        except ParseFailed as exc:
            self._log_failure(len(content), exc.__cause__, exc.conversion_status)
            raise
        except InvalidFile, ModelUnavailable, ParserBusy:
            raise
        except Exception as exc:  # noqa: BLE001 - what a parser raises is unknown; the answer is ParseFailed
            # A parser that breaks its contract: its error can quote the document, so only the type is kept.
            self._log_failure(len(content), exc)
            raise ParseFailed from None
        log.info(
            "document_parsed",
            file_size_bytes=len(content),
            page_count=result.page_count,
            elapsed_ms=result.elapsed_ms,
            status="ok",
        )
        text = result.text if output_format is OutputFormat.MARKDOWN else result.plain_text
        return ParsedDocument(
            text=text, page_count=result.page_count, elapsed_ms=result.elapsed_ms, model=result.model_id
        )

    def _parse(self, content: bytes, extension: str) -> ParseResult:
        """Call the parser and refuse a result the response cannot carry, as a failure of the parser."""
        result = self._parser.parse(content, f"upload.{extension}")
        if result.page_count < 0 or result.elapsed_ms < 0:
            msg = "negative page count or time"
            raise ValueError(msg)
        return result

    @staticmethod
    def _log_failure(size: int, cause: BaseException | None, conversion_status: str | None = None) -> None:
        """End the one event of a document that failed; the error itself is logged once, by the handler.

        No traceback and no message: a library error can quote the document it failed on.
        """
        log.info(
            "document_parsed",
            file_size_bytes=size,
            status="failed",
            cause_type=type(cause).__name__ if cause is not None else None,
            conversion_status=conversion_status,
        )
