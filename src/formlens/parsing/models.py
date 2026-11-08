"""What the service knows about a document: its type, the output the client asks for, the result."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Final


class DocumentType(StrEnum):
    """The formats the service accepts."""

    PDF = "pdf"
    PNG = "png"
    JPEG = "jpeg"
    TIFF = "tiff"

    @property
    def extension(self) -> str:
        """Return the file extension Docling recognises the format by."""
        return {"pdf": "pdf", "png": "png", "jpeg": "jpg", "tiff": "tiff"}[self.value]


class OutputFormat(StrEnum):
    """How the extracted text is returned."""

    MARKDOWN = "markdown"
    TEXT = "text"


@dataclass(frozen=True, slots=True)
class ParsedDocument:
    """The answer of the service: the text in the requested format and how it was made."""

    text: str
    page_count: int
    elapsed_ms: int
    model: str


_PDF_WINDOW: Final = 1024  # the PDF specification lets the header sit within the first 1024 bytes
_SIGNATURES: Final = (
    (b"\x89PNG\r\n\x1a\n", DocumentType.PNG),
    (b"\xff\xd8\xff", DocumentType.JPEG),
    (b"II*\x00", DocumentType.TIFF),
    (b"MM\x00*", DocumentType.TIFF),
)


def detect_document_type(content: bytes) -> DocumentType | None:
    """Tell the document type from its first bytes; the client's Content-Type and name are never used."""
    if b"%PDF-" in content[:_PDF_WINDOW]:
        return DocumentType.PDF
    for signature, kind in _SIGNATURES:
        if content.startswith(signature):
            return kind
    return None
