import pytest

from formlens.parsing.models import DocumentType, detect_document_type
from tests.documents import sample


@pytest.mark.parametrize(
    ("name", "kind"),
    [
        ("text_layer.pdf", DocumentType.PDF),
        ("scan.pdf", DocumentType.PDF),
        ("sample.png", DocumentType.PNG),
        ("sample.jpg", DocumentType.JPEG),
        ("sample.tiff", DocumentType.TIFF),
    ],
)
def test_the_sample_documents_are_typed_by_their_bytes(name: str, kind: DocumentType) -> None:
    assert detect_document_type(sample(name)) is kind


@pytest.mark.parametrize(
    ("content", "kind"),
    [
        pytest.param(b"%PDF-1.7", DocumentType.PDF, id="pdf"),
        pytest.param(b"x" * 1019 + b"%PDF-", DocumentType.PDF, id="pdf-header-after-1019-bytes-of-junk"),
        pytest.param(b"\x89PNG\r\n\x1a\n", DocumentType.PNG, id="png"),
        pytest.param(b"\xff\xd8\xff\xe0", DocumentType.JPEG, id="jpeg"),
        pytest.param(b"II*\x00", DocumentType.TIFF, id="tiff-little-endian"),
        pytest.param(b"MM\x00*", DocumentType.TIFF, id="tiff-big-endian"),
    ],
)
def test_each_signature_is_recognised(content: bytes, kind: DocumentType) -> None:
    assert detect_document_type(content) is kind


@pytest.mark.parametrize(
    "content",
    [
        pytest.param(b"", id="empty"),
        pytest.param(b"hello world", id="text"),
        pytest.param(b"GIF89a", id="gif"),
        pytest.param(b"x" * 1020 + b"%PDF-", id="pdf-header-past-the-first-1024-bytes"),
        pytest.param(b"\x89PNG", id="truncated-png-signature"),
        pytest.param(b"<html></html>", id="html"),
    ],
)
def test_anything_else_has_no_type(content: bytes) -> None:
    assert detect_document_type(content) is None


@pytest.mark.parametrize(
    ("kind", "extension"),
    [(DocumentType.PDF, "pdf"), (DocumentType.PNG, "png"), (DocumentType.JPEG, "jpg"), (DocumentType.TIFF, "tiff")],
)
def test_each_type_has_the_extension_docling_knows_it_by(kind: DocumentType, extension: str) -> None:
    assert kind.extension == extension
