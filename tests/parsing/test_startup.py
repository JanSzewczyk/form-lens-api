"""The parser is loaded when the app starts, off the event loop, and a failure stops the start."""

import asyncio
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from formlens.config import Settings
from formlens.main import create_app
from formlens.parsing.exceptions import ModelUnavailable
from formlens.parsing.ports import DocumentParser
from tests.conftest import make_settings
from tests.documents import sample
from tests.fakes import FakeParser


def test_the_factory_runs_once_at_startup_in_a_worker_thread_and_receives_the_settings() -> None:
    received: list[Settings] = []
    on_the_event_loop: list[bool] = []
    parser = FakeParser()
    settings = make_settings(vlm_backend="transformers")

    def factory(given: Settings) -> DocumentParser:
        received.append(given)
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            on_the_event_loop.append(False)
        else:
            on_the_event_loop.append(True)
        return parser

    app = create_app(settings, parser_factory=factory)
    before_start = app.state.parser

    with TestClient(app) as client:
        loaded = app.state.parser
        client.post("/v1/documents/parse", files={"file": ("a.png", sample("sample.png"), "image/png")})
        client.post("/v1/documents/parse", files={"file": ("a.png", sample("sample.png"), "image/png")})

    assert before_start is None  # building the app loads nothing
    assert loaded is parser
    assert received == [settings]
    assert on_the_event_loop == [False]
    assert len(parser.calls) == 2
    assert app.state.parser is None  # released at shutdown


def test_a_factory_that_fails_stops_the_startup_and_logs_once_with_a_hint(
    capsys: pytest.CaptureFixture[str],
) -> None:
    def factory(_: Settings) -> DocumentParser:
        raise ModelUnavailable

    app = create_app(make_settings(vlm_backend="transformers", models_path="/data/models"), parser_factory=factory)

    with pytest.raises(ModelUnavailable), TestClient(app):
        pass

    events = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.startswith("{")]
    [failed] = [e for e in events if e["event"] == "model_load_failed"]
    assert failed["backend"] == "transformers"
    assert failed["models_path"] == "/data/models"
    assert failed["reason"] == "The document model is not available."
    assert "make download-models" in failed["hint"]
    assert failed["level"] == "error"


def test_the_default_factory_refuses_an_empty_models_folder_before_it_imports_docling(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    app = create_app(make_settings(models_path=tmp_path, vlm_backend="transformers"))

    with pytest.raises(ModelUnavailable, match=r"missing config\.json"), TestClient(app):
        pass

    events = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.startswith("{")]
    [failed] = [e for e in events if e["event"] == "model_load_failed"]
    assert failed["models_path"] == str(tmp_path)
    assert "ibm-granite/granite-docling-258M" in failed["reason"]


def test_a_failure_that_is_not_a_missing_model_logs_no_download_hint(capsys: pytest.CaptureFixture[str]) -> None:
    def factory(_: Settings) -> DocumentParser:
        msg = "out of memory"
        raise RuntimeError(msg)

    app = create_app(make_settings(), parser_factory=factory)

    with pytest.raises(RuntimeError, match="out of memory"), TestClient(app):
        pass

    events = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.startswith("{")]
    [failed] = [e for e in events if e["event"] == "model_load_failed"]
    assert failed["reason"] == "out of memory"
    assert "hint" not in failed
