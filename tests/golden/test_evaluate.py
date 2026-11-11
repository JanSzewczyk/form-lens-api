"""`make evaluate` without a model: the run, the cache and what it says when Ollama or the models are missing."""

import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, ClassVar

import pytest

from formlens.extractions.adapters.ollama_extractor import PROMPT_VERSION
from formlens.extractions.domain.exceptions import LlmUnavailable
from formlens.extractions.domain.model import TemplateSnapshot
from tests.conftest import make_settings
from tests.extractions.fakes import FakeTextSource
from tests.golden.evaluate import (
    NotReadyError,
    cached_text,
    check_ollama,
    docling_text_source,
    evaluate,
    main,
    snapshot,
)
from tests.golden.generator import GoldenDocument, generate
from tests.golden.templates import TEMPLATES

DOCS = generate()[:6]
BY_TEXT = {doc.id: doc for doc in DOCS}


class Oracle:
    """An extractor that knows the answers: the text it is given is the id of the document."""

    def __init__(self, *, invent: bool = False) -> None:
        self.invent = invent

    def extract(self, text: str, template: TemplateSnapshot) -> dict[str, Any]:
        expected = BY_TEXT[text].expected
        return {k: ("invented" if self.invent and v is None else v) for k, v in expected.items()}


class Down:
    def extract(self, text: str, template: TemplateSnapshot) -> dict[str, Any]:
        raise LlmUnavailable("ConnectError")


def id_as_text(doc: GoldenDocument) -> str:
    return doc.id


def test_a_model_that_knows_every_answer_scores_full_marks() -> None:
    report = evaluate(DOCS, id_as_text, Oracle())

    assert (report.exact_match, report.null_precision, report.invented) == (1.0, 1.0, 0)
    assert report.documents == len(DOCS)


def test_a_model_that_invents_a_value_for_every_empty_field_is_caught_by_null_precision() -> None:
    report = evaluate(DOCS, id_as_text, Oracle(invent=True))

    assert report.exact_match == 1.0
    assert report.null_precision == 0.0
    assert report.invented > 0


def test_a_document_the_model_fails_on_is_counted_and_its_message_is_not_kept() -> None:
    report = evaluate(DOCS, id_as_text, Down())

    assert report.failed_documents == [d.id for d in DOCS]
    assert report.exact_match == 0.0


def test_the_snapshot_of_a_template_carries_its_fields_and_the_generated_schema() -> None:
    item = snapshot("zgoda", TEMPLATES["zgoda"])

    assert [f.name for f in item.fields] == ["pesel", "data_od", "zgoda", "imie_nazwisko", "miasto"]
    assert item.json_schema["required"] == [f.name for f in item.fields]
    assert snapshot("zgoda", TEMPLATES["zgoda"]).template_id == item.template_id


# --- the text cache --------------------------------------------------------------------------------


def test_the_text_of_a_document_is_read_once_and_then_taken_from_the_cache(tmp_path: Path) -> None:
    source = FakeTextSource("parsed text")
    read = cached_text(source, tmp_path, refresh=False)

    first, second = read(DOCS[0]), read(DOCS[0])

    assert (first, second, source.calls) == ("parsed text", "parsed text", 1)


def test_a_changed_document_is_not_served_from_the_cache_of_the_old_one(tmp_path: Path) -> None:
    source = FakeTextSource("parsed text")
    read = cached_text(source, tmp_path, refresh=False)
    read(DOCS[0])
    changed = GoldenDocument(DOCS[0].id, DOCS[0].template, DOCS[0].kind, DOCS[0].lines, DOCS[0].expected, b"%PDF other")

    read(changed)

    assert source.calls == 2


def test_refreshing_parses_again(tmp_path: Path) -> None:
    source = FakeTextSource("parsed text")
    cached_text(source, tmp_path, refresh=False)(DOCS[0])

    cached_text(source, tmp_path, refresh=True)(DOCS[0])

    assert source.calls == 2


# --- main ------------------------------------------------------------------------------------------


def test_main_prints_the_table_and_writes_the_markdown_section(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    class Nothing:
        def extract(self, text: str, template: TemplateSnapshot) -> dict[str, Any]:
            return {item.name: None for item in template.fields}

    output = tmp_path / "report.md"

    code = main(
        ["--limit", "3", "--output", str(output)],
        settings=make_settings(llm_model="qwen3:8b"),
        text_source=FakeTextSource("some text"),
        extractor=Nothing(),
        cache_dir=tmp_path / "cache",
    )

    shown = capsys.readouterr().out
    section = output.read_text(encoding="utf-8")
    assert code == 0
    assert "documents            3" in shown
    assert "null precision       100.0%" in shown
    assert "`qwen3:8b`" in section
    assert f"prompt `{PROMPT_VERSION}`" in section
    assert "3 synthetic documents" in section


class Handler(BaseHTTPRequestHandler):
    models: ClassVar[list[str]] = []
    garbage: ClassVar[bool] = False

    def do_GET(self) -> None:
        body = (
            b"<html>" if type(self).garbage else json.dumps({"data": [{"id": n} for n in type(self).models]}).encode()
        )
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        """Say nothing."""


@pytest.fixture
def ollama() -> Iterator[tuple[str, type[Handler]]]:
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}/v1", Handler
    httpd.shutdown()
    httpd.server_close()
    thread.join(5)


def test_an_ollama_that_is_not_running_stops_the_run_with_what_to_do(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    code = main(
        ["--output", str(tmp_path / "r.md")],
        settings=make_settings(llm_base_url="http://127.0.0.1:1/v1"),
        text_source=FakeTextSource(),
    )

    err = capsys.readouterr().err
    assert code == 2
    assert "ollama serve" in err
    assert "ollama pull qwen3:8b" in err
    assert not (tmp_path / "r.md").exists()  # no numbers from a run that did not happen


def test_a_model_that_is_not_pulled_stops_the_run_and_names_it(ollama: tuple[str, type[Handler]]) -> None:
    url, handler = ollama
    handler.models = ["another:1b"]

    with pytest.raises(NotReadyError, match=r"ollama pull qwen3:8b"):
        check_ollama(url, "qwen3:8b")


def test_an_answer_that_does_not_list_models_is_not_a_reason_to_stop(ollama: tuple[str, type[Handler]]) -> None:
    url, handler = ollama
    handler.models = []
    handler.garbage = True
    try:
        check_ollama(url, "qwen3:8b")
    finally:
        handler.garbage = False


def test_a_pulled_model_passes_the_check(ollama: tuple[str, type[Handler]]) -> None:
    url, handler = ollama
    handler.models = ["qwen3:8b"]

    check_ollama(url, "qwen3:8b")


def test_missing_document_models_stop_the_run_with_what_to_do(tmp_path: Path) -> None:
    settings = make_settings(models_path=tmp_path, vlm_backend="transformers")

    with pytest.raises(NotReadyError, match="make download-models"):
        docling_text_source(settings)


def test_main_without_the_document_models_exits_with_the_message(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    code = main(
        ["--limit", "2", "--output", str(tmp_path / "r.md")],
        settings=make_settings(models_path=tmp_path, vlm_backend="transformers"),
        extractor=Oracle(),
        cache_dir=tmp_path / "empty-cache",
    )

    assert code == 2
    assert "make download-models" in capsys.readouterr().err


def test_main_with_every_text_cached_does_not_load_the_document_model(tmp_path: Path) -> None:
    source = FakeTextSource("cached text")
    cache = tmp_path / "cache"
    docs = generate()[:2]
    for doc in docs:
        cached_text(source, cache, refresh=False)(doc)

    class Nothing:
        def extract(self, text: str, template: TemplateSnapshot) -> dict[str, Any]:
            return {item.name: None for item in template.fields}

    code = main(
        ["--limit", "2", "--output", str(tmp_path / "r.md")],
        settings=make_settings(models_path=tmp_path, vlm_backend="transformers"),  # no models here
        extractor=Nothing(),
        cache_dir=cache,
    )

    assert code == 0
