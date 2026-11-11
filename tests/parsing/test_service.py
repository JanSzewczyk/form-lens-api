import pytest
from structlog.testing import capture_logs

from formlens.parsing.exceptions import FileTooLarge, InvalidFile, ParseFailed, ParserBusy, UnsupportedMediaType
from formlens.parsing.models import BYTES_PER_MB, DocumentType, OutputFormat
from formlens.parsing.ports import ParseResult
from formlens.parsing.service import DocumentService
from formlens.parsing.slots import ParseSlots
from tests.documents import png_of_size, sample
from tests.fakes import FakeParser

RESULT = ParseResult(text="# Heading", plain_text="Heading", page_count=3, elapsed_ms=250, model_id="acme/model-1")


def make_service(parser: FakeParser, *, slots: int = 1, max_upload_mb: int = 1) -> DocumentService:
    return DocumentService(parser, ParseSlots(slots), max_upload_mb=max_upload_mb)


def test_markdown_is_the_text_of_the_markdown_output() -> None:
    service = make_service(FakeParser(RESULT))

    parsed = service.parse(sample("sample.png"), OutputFormat.MARKDOWN)

    assert (parsed.text, parsed.page_count, parsed.elapsed_ms, parsed.model) == ("# Heading", 3, 250, "acme/model-1")


def test_the_text_output_is_the_plain_text() -> None:
    service = make_service(FakeParser(RESULT))

    assert service.parse(sample("sample.png"), OutputFormat.TEXT).text == "Heading"


@pytest.mark.parametrize(
    ("name", "neutral"),
    [
        ("text_layer.pdf", "upload.pdf"),
        ("sample.png", "upload.png"),
        ("sample.jpg", "upload.jpg"),
        ("sample.tiff", "upload.tiff"),
    ],
)
def test_the_parser_gets_a_neutral_name_chosen_from_the_bytes(name: str, neutral: str) -> None:
    parser = FakeParser()
    content = sample(name)

    make_service(parser).parse(content, OutputFormat.MARKDOWN)

    assert parser.calls == [(len(content), neutral)]


@pytest.mark.parametrize(
    ("name", "kind"),
    [
        ("text_layer.pdf", DocumentType.PDF),
        ("sample.png", DocumentType.PNG),
        ("sample.jpg", DocumentType.JPEG),
        ("sample.tiff", DocumentType.TIFF),
    ],
)
def test_validate_returns_the_type_of_a_document_it_accepts_without_parsing_it(name: str, kind: DocumentType) -> None:
    parser = FakeParser()

    assert make_service(parser).validate(sample(name)) == kind
    assert parser.calls == []


def test_validate_refuses_in_the_order_empty_then_size_then_type_and_never_reaches_the_parser() -> None:
    parser = FakeParser()
    service = make_service(parser, max_upload_mb=1)

    with pytest.raises(InvalidFile, match="empty"):
        service.validate(b"")
    with pytest.raises(FileTooLarge, match="1 MB"):
        service.validate(b"x" * (BYTES_PER_MB + 1))  # too large and of no known type: the size wins
    with pytest.raises(UnsupportedMediaType):
        service.validate(b"just some text")

    assert parser.calls == []


def test_validate_accepts_a_file_of_exactly_the_limit_and_refuses_one_byte_more() -> None:
    service = make_service(FakeParser(), max_upload_mb=1)

    assert service.validate(png_of_size(BYTES_PER_MB)) == DocumentType.PNG
    with pytest.raises(FileTooLarge):
        service.validate(png_of_size(BYTES_PER_MB + 1))


def test_an_empty_file_is_invalid_before_anything_else_is_asked() -> None:
    parser = FakeParser()

    with pytest.raises(InvalidFile, match="empty"):
        make_service(parser).parse(b"", OutputFormat.MARKDOWN)

    assert parser.calls == []


def test_a_file_of_exactly_the_limit_is_accepted_and_one_byte_more_is_refused() -> None:
    parser = FakeParser()
    service = make_service(parser, max_upload_mb=1)

    service.parse(png_of_size(BYTES_PER_MB), OutputFormat.MARKDOWN)
    with pytest.raises(FileTooLarge, match="1 MB"):
        service.parse(png_of_size(BYTES_PER_MB + 1), OutputFormat.MARKDOWN)

    assert len(parser.calls) == 1


def test_the_size_is_checked_before_the_type() -> None:
    with pytest.raises(FileTooLarge):
        make_service(FakeParser()).parse(b"x" * (BYTES_PER_MB + 1), OutputFormat.MARKDOWN)


def test_content_of_an_unknown_type_is_refused_without_reaching_the_parser() -> None:
    parser = FakeParser()

    with pytest.raises(UnsupportedMediaType):
        make_service(parser).parse(b"just some text", OutputFormat.MARKDOWN)

    assert parser.calls == []


def test_a_busy_parser_is_refused_with_the_time_to_wait() -> None:
    slots = ParseSlots(1)
    parser = FakeParser()
    service = DocumentService(parser, slots, max_upload_mb=1)

    with slots.hold(), pytest.raises(ParserBusy) as busy:
        service.parse(sample("sample.png"), OutputFormat.MARKDOWN)

    assert busy.value.retry_after_seconds == 5
    assert parser.calls == []


def test_a_slot_is_free_again_after_the_parser_failed() -> None:
    parser = FakeParser(error=ParseFailed())
    service = make_service(parser, slots=1)

    with pytest.raises(ParseFailed):
        service.parse(sample("sample.png"), OutputFormat.MARKDOWN)
    with pytest.raises(ParseFailed):
        service.parse(sample("sample.png"), OutputFormat.MARKDOWN)

    assert len(parser.calls) == 2  # the second call got in: the first one gave its slot back


def test_one_event_says_how_big_the_file_was_and_how_long_the_model_took() -> None:
    content = sample("sample.png")

    with capture_logs() as events:
        make_service(FakeParser(RESULT)).parse(content, OutputFormat.MARKDOWN)

    assert events == [
        {
            "event": "document_parsed",
            "log_level": "info",
            "file_size_bytes": len(content),
            "page_count": 3,
            "elapsed_ms": 250,
            "status": "ok",
        }
    ]


def test_a_failed_parse_ends_the_one_document_event_with_the_type_of_its_cause_and_never_its_text() -> None:
    failure = ParseFailed()
    failure.__cause__ = RuntimeError("secret-marker-4417")

    with capture_logs() as events, pytest.raises(ParseFailed):
        make_service(FakeParser(error=failure)).parse(sample("sample.png"), OutputFormat.MARKDOWN)

    [event] = events
    assert event["event"] == "document_parsed"
    assert (event["status"], event["cause_type"], event["log_level"]) == ("failed", "RuntimeError", "info")
    assert "secret-marker-4417" not in str(event)


@pytest.mark.parametrize("status", ["failure", "partial_success"], ids=["failed-conversion", "timeout-or-partial"])
def test_the_failure_event_names_the_status_the_conversion_ended_with(status: str) -> None:
    """A timeout, a partial result and a failure all end as a `RuntimeError`; the status tells them apart."""
    with capture_logs() as events, pytest.raises(ParseFailed):
        make_service(FakeParser(error=ParseFailed(status))).parse(sample("sample.png"), OutputFormat.MARKDOWN)

    [event] = events
    assert event["conversion_status"] == status


def test_a_failure_that_is_not_a_conversion_status_logs_none() -> None:
    with capture_logs() as events, pytest.raises(ParseFailed):
        make_service(FakeParser(error=RuntimeError("x"))).parse(sample("sample.png"), OutputFormat.MARKDOWN)

    [event] = events
    assert (event["cause_type"], event["conversion_status"]) == ("RuntimeError", None)
