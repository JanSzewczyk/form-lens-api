import json
from pathlib import Path

import pytest

from scripts import export_openapi


def test_rendered_document_is_stable_and_sorted() -> None:
    first = export_openapi.render()

    assert first == export_openapi.render()
    assert first.endswith("}\n")
    assert list(json.loads(first)) == sorted(json.loads(first))


def test_export_writes_the_document_and_check_accepts_it(tmp_path: Path) -> None:
    target = tmp_path / "openapi.json"

    assert export_openapi.main([str(target)]) == 0
    assert export_openapi.main(["--check", str(target)]) == 0
    assert json.loads(target.read_text(encoding="utf-8"))["info"]["title"] == "formlens"


def test_check_fails_for_a_stale_or_missing_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    stale = tmp_path / "openapi.json"
    stale.write_text("{}\n", encoding="utf-8")

    assert export_openapi.main(["--check", str(stale)]) == 1
    assert export_openapi.main(["--check", str(tmp_path / "missing.json")]) == 1
    assert "make openapi" in capsys.readouterr().err


def test_the_committed_document_is_current() -> None:
    assert export_openapi.main(["--check"]) == 0


def test_the_document_ignores_environment_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_NAME", "orders")
    monkeypatch.setenv("DOCS_ENABLED", "true")

    assert json.loads(export_openapi.render())["info"]["title"] == "formlens"
    assert export_openapi.main(["--check"]) == 0
