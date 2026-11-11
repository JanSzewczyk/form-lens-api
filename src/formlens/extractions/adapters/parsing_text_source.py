"""The extractions' view of document parsing: the checks and the text, with parsing's errors translated."""

from formlens.extractions.domain import exceptions as domain
from formlens.parsing import exceptions as parsing
from formlens.parsing.models import OutputFormat
from formlens.parsing.service import DocumentService


class ParsingTextSource:
    """Reads text through the same `DocumentService` (and so the same parser slots) as the parse endpoint."""

    def __init__(self, service: DocumentService, *, max_upload_mb: int) -> None:
        """Wire the parsing service and the upload limit it enforces."""
        self._service = service
        self._max_upload_mb = max_upload_mb

    def check(self, content: bytes) -> None:
        """Refuse an upload that cannot be parsed, without parsing it."""
        try:
            self._service.validate(content)
        except parsing.InvalidFile:
            raise domain.UploadEmpty from None
        except parsing.FileTooLarge:
            raise domain.UploadTooLarge(self._max_upload_mb) from None
        except parsing.UnsupportedMediaType:
            raise domain.UploadUnsupported from None

    def extract_text(self, content: bytes) -> str:
        """Return the plain text of the document."""
        try:
            return self._service.parse(content, OutputFormat.TEXT).text
        except parsing.InvalidFile:
            raise domain.FileUnreadable("InvalidFile") from None
        except parsing.FileTooLarge, parsing.UnsupportedMediaType:
            raise domain.FileUnreadable("refused") from None
        except parsing.ParserBusy:
            raise domain.ParserBusy from None
        except parsing.ParseFailed as exc:
            raise domain.ParseFailed(exc.conversion_status) from None
        except parsing.ModelUnavailable:
            raise domain.ParseFailed("ModelUnavailable") from None
