"""The golden set: it is the same every time, varied as promised, and its answers are right about its pages."""

import json
import random
from pathlib import Path

import pypdfium2  # type: ignore[import-untyped]  # pdfium has no type information
from jsonschema import Draft202012Validator

from formlens.patterns import matches
from formlens.templates.json_schema import build_json_schema
from tests.golden.generator import SEED, export, generate, render_scan
from tests.golden.templates import TEMPLATES, body_of

DOCS = generate()  # made once: the tests only read it


def seeded() -> random.Random:
    return random.Random(1)  # noqa: S311  # test data, not a secret


def text_of_pdf(content: bytes) -> str:
    pdf = pypdfium2.PdfDocument(content)
    try:
        page = pdf[0]
        text = page.get_textpage().get_text_range()
        page.close()
        return str(text)
    finally:
        pdf.close()


def test_the_set_has_between_twenty_and_fifty_documents_with_unique_ids() -> None:
    docs = DOCS

    assert 20 <= len(docs) <= 50
    assert len({d.id for d in docs}) == len(docs)
    assert {d.template for d in docs} == set(TEMPLATES)


def test_the_same_seed_gives_the_same_documents_byte_for_byte_and_another_seed_gives_others() -> None:
    first, again, other = DOCS, generate(), generate(seed=SEED + 1)

    assert [(d.id, d.content, d.expected) for d in first] == [(d.id, d.content, d.expected) for d in again]
    assert [d.expected for d in first] != [d.expected for d in other]


def test_every_field_of_every_template_is_absent_in_at_least_one_document() -> None:
    docs = DOCS

    for key, fields in TEMPLATES.items():
        for item in fields:
            assert any(d.expected[item.name] is None for d in docs if d.template == key), (key, item.name)


def test_every_expected_answer_has_the_keys_of_its_template_and_satisfies_its_schema() -> None:
    for doc in DOCS:
        fields = TEMPLATES[doc.template]
        assert set(doc.expected) == {f.name for f in fields}, doc.id
        assert Draft202012Validator(build_json_schema(fields)).is_valid(doc.expected), doc.id


def test_the_set_is_varied_text_and_scans_present_and_absent_fields_and_polish_letters() -> None:
    docs = DOCS

    assert {d.kind for d in docs} == {"text-pdf", "scan-png", "scan-jpeg", "scan-pdf"}
    for key in TEMPLATES:
        mine = [d for d in docs if d.template == key]
        assert any(None in d.expected.values() for d in mine), f"{key} has no absent field"
        assert any(None not in d.expected.values() for d in mine), f"{key} has no complete document"
    assert any(char in "ąćęłńóśźż" for d in docs for line in d.lines for char in line)


def test_a_field_the_document_does_not_show_is_expected_null_and_its_value_is_not_on_the_page() -> None:
    for doc in DOCS:
        text = " ".join(doc.lines)
        for name, value in doc.expected.items():
            if isinstance(value, str) and name not in {"data_od", "data_wystawienia", "data_zlozenia"}:
                assert value in text, (doc.id, name)
    consent = [d for d in DOCS if d.template == "zgoda" and d.expected["pesel"] is None]
    assert consent
    assert all("PESEL: ..........." in d.lines for d in consent)


def test_every_pesel_is_obviously_synthetic_and_fits_the_template_pattern() -> None:
    pesels = [d.expected["pesel"] for d in DOCS if d.template == "zgoda" and d.expected["pesel"] is not None]

    assert pesels
    assert all(p.startswith("000000") and matches("^[0-9]{11}$", p) for p in pesels)


def test_every_page_says_it_is_a_test_document() -> None:
    assert all(any("syntetyczne" in line for line in d.lines) for d in DOCS)


def test_a_text_pdf_has_a_real_text_layer_that_returns_every_line_with_its_polish_letters() -> None:
    text_pdfs = [d for d in DOCS if d.kind == "text-pdf"]

    assert text_pdfs
    for doc in text_pdfs:
        extracted = " ".join(text_of_pdf(doc.content).split())  # pdfium folds a run of spaces into one
        for line in doc.lines:
            assert " ".join(line.split()) in extracted, (doc.id, line)


def test_a_scanned_pdf_has_no_text_layer_and_the_images_have_their_signature() -> None:
    docs = DOCS
    scan_pdf = next(d for d in docs if d.kind == "scan-pdf")
    png = next(d for d in docs if d.kind == "scan-png")
    jpeg = next(d for d in docs if d.kind == "scan-jpeg")

    assert text_of_pdf(scan_pdf.content).strip() == ""
    assert png.content.startswith(b"\x89PNG")
    assert jpeg.content.startswith(b"\xff\xd8")
    assert {d.extension for d in docs} == {"pdf", "png", "jpg"}


def test_the_scan_draws_polish_letters_that_the_font_cannot() -> None:
    plain = render_scan(("zazolc",), seeded(), "png")
    polish = render_scan(("zażółć",), seeded(), "png")

    assert plain != polish
    assert render_scan(("zażółć",), seeded(), "png") == polish


def test_export_writes_each_document_and_its_expected_answer(tmp_path: Path) -> None:
    docs = DOCS[:4]

    export(docs, tmp_path / "out")

    written = sorted(p.name for p in (tmp_path / "out").iterdir())
    assert written == sorted([f"{d.id}.{d.extension}" for d in docs] + [f"{d.id}.expected.json" for d in docs])
    assert json.loads((tmp_path / "out" / f"{docs[0].id}.expected.json").read_text()) == docs[0].expected


def test_the_request_body_of_a_template_is_accepted_by_the_api(client: object) -> None:
    from fastapi.testclient import TestClient

    assert isinstance(client, TestClient)
    for key in TEMPLATES:
        response = client.post("/v1/templates", json=body_of(key))

        assert response.status_code == 201, (key, response.text)
