"""The two adapters that look at other modules: templates and parsing."""

from uuid import UUID

import pytest

from formlens.database import Database
from formlens.extractions.adapters.parsing_text_source import ParsingTextSource
from formlens.extractions.adapters.template_catalog import TemplateServiceCatalog
from formlens.extractions.domain import exceptions as domain
from formlens.parsing import exceptions as parsing
from formlens.parsing.ports import ParseResult
from formlens.parsing.service import DocumentService
from formlens.parsing.slots import ParseSlots
from formlens.templates.json_schema import build_json_schema
from formlens.templates.models import FieldType, TemplateField
from formlens.templates.repository import SqliteTemplateRepository
from formlens.templates.service import TemplateService
from tests.documents import png_of_size, sample
from tests.fakes import FakeParser
from tests.templates.factories import TemplateDraftFactory

RESULT = ParseResult(text="# Markdown", plain_text="Plain text", page_count=1, elapsed_ms=5, model_id="m")


def text_source(parser: FakeParser, *, slots: int = 1, max_mb: int = 1) -> ParsingTextSource:
    service = DocumentService(parser, ParseSlots(slots), max_upload_mb=max_mb)
    return ParsingTextSource(service, max_upload_mb=max_mb)


# --- templates -------------------------------------------------------------------------------------


def test_the_catalog_copies_a_template_as_plain_data_with_its_generated_schema(database: Database) -> None:
    service = TemplateService(SqliteTemplateRepository(database))
    fields = (
        TemplateField("number", FieldType.TEXT, description="top right", required=True),
        TemplateField("state", FieldType.CHOICE, allowed_values=("open", "closed")),
    )
    created = service.create(TemplateDraftFactory.build(name="Invoice", fields=fields))
    service.replace(created.id, TemplateDraftFactory.build(name="Invoice", fields=fields))

    snapshot = TemplateServiceCatalog(service).snapshot(created.id)

    assert (snapshot.template_id, snapshot.version, snapshot.name) == (created.id, 2, "Invoice")
    assert [(f.name, f.type, f.description, f.required) for f in snapshot.fields] == [
        ("number", "text", "top right", True),
        ("state", "choice", "", False),
    ]
    assert snapshot.json_schema == build_json_schema(fields)


def test_the_catalog_says_which_template_is_missing(database: Database) -> None:
    catalog = TemplateServiceCatalog(TemplateService(SqliteTemplateRepository(database)))

    with pytest.raises(domain.TemplateMissing) as raised:
        catalog.snapshot(UUID(int=77))

    assert raised.value.template_id == UUID(int=77)


# --- parsing ---------------------------------------------------------------------------------------


def test_the_text_source_returns_the_plain_text_not_the_markdown() -> None:
    parser = FakeParser(RESULT)

    assert text_source(parser).extract_text(sample("sample.png")) == "Plain text"


def test_the_checks_translate_parsings_refusals_and_never_reach_the_parser() -> None:
    parser = FakeParser()
    source = text_source(parser, max_mb=1)

    with pytest.raises(domain.UploadEmpty):
        source.check(b"")
    with pytest.raises(domain.UploadTooLarge) as large:
        source.check(png_of_size(1024 * 1024 + 1))
    with pytest.raises(domain.UploadUnsupported):
        source.check(b"plain text")
    source.check(sample("sample.png"))

    assert large.value.limit_mb == 1
    assert parser.calls == []


@pytest.mark.parametrize(
    ("raised", "expected", "cause"),
    [
        (parsing.InvalidFile(), domain.FileUnreadable, "InvalidFile"),
        (RuntimeError("PRIVATE"), domain.ParseFailed, None),
    ],
    ids=["unreadable", "parser-broke-its-contract"],
)
def test_a_parser_error_becomes_the_matching_job_error(
    raised: Exception, expected: type[domain.JobError], cause: str | None
) -> None:
    with pytest.raises(expected) as caught:
        text_source(FakeParser(error=raised)).extract_text(sample("sample.png"))

    assert "PRIVATE" not in str(caught.value)
    assert caught.value.__cause__ is None
    if cause is not None:
        assert caught.value.cause_type == cause


def test_a_failed_conversion_keeps_its_status_as_the_cause_type() -> None:
    parser = FakeParser(error=parsing.ParseFailed("partial_success"))

    with pytest.raises(domain.ParseFailed) as caught:
        text_source(parser).extract_text(sample("sample.png"))

    assert caught.value.cause_type == "partial_success"


def test_no_free_slot_is_a_busy_parser() -> None:
    source = text_source(FakeParser(), slots=0)

    with pytest.raises(domain.ParserBusy):
        source.extract_text(sample("sample.png"))


def test_an_unloaded_model_is_a_failure_a_retry_may_cure() -> None:
    parser = FakeParser(error=parsing.ModelUnavailable())

    with pytest.raises(domain.ParseFailed) as caught:
        text_source(parser).extract_text(sample("sample.png"))

    assert caught.value.cause_type == "ModelUnavailable"
