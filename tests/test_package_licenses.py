"""The script that reads a package's declared licence from its metadata."""

import runpy
import sys
from importlib import metadata

import pytest

from scripts.package_licenses import declared_licence, main


def test_a_package_that_declares_a_licence_expression_gives_it() -> None:
    version, licence, source = declared_licence("pytest")

    assert version
    assert licence == "MIT"
    assert source == "License-Expression"


def test_every_package_gets_a_value_and_the_field_it_came_from() -> None:
    for name in ("sqlalchemy", "alembic", "httpx2", "jsonschema", "mako"):
        version, licence, source = declared_licence(name)

        assert version
        assert licence
        assert source in {"License-Expression", "License", "Classifier", "none"}


def test_the_rows_are_printed_and_an_unknown_package_is_marked_and_fails(capsys: pytest.CaptureFixture[str]) -> None:
    status = main(["pytest", "no-such-package-xyz"])

    lines = capsys.readouterr().out.splitlines()
    assert status == 1
    assert lines[0].startswith("| pytest | ")
    assert lines[0].endswith("| License-Expression |")
    assert lines[1] == "| no-such-package-xyz | not installed | - | - |"


class FakeInfo:
    """Just enough of an email message: `get`, `get_all`."""

    def __init__(self, **fields: object) -> None:
        self.fields = fields

    def get(self, name: str) -> str | None:
        value = self.fields.get(name)
        return value if isinstance(value, str) else None

    def get_all(self, name: str) -> list[str] | None:
        value = self.fields.get(name)
        return value if isinstance(value, list) else None


@pytest.mark.parametrize(
    ("fields", "expected"),
    [
        ({"License": "BSD"}, ("1.0", "BSD", "License")),
        (
            {"License": "x" * 200, "Classifier": ["License :: OSI Approved :: MIT License", "Topic :: x"]},
            ("1.0", "OSI Approved :: MIT License", "Classifier"),
        ),
        ({"License": "line one\nline two"}, ("1.0", "not declared in the metadata", "none")),
        ({}, ("1.0", "not declared in the metadata", "none")),
    ],
    ids=["short-field", "long-text-falls-back-to-classifier", "licence-text-is-not-a-name", "nothing"],
)
def test_the_licence_falls_back_from_the_expression_to_the_field_to_the_classifier(
    monkeypatch: pytest.MonkeyPatch, fields: dict[str, object], expected: tuple[str, str, str]
) -> None:
    monkeypatch.setattr(metadata, "metadata", lambda _name: FakeInfo(**fields))
    monkeypatch.setattr(metadata, "version", lambda _name: "1.0")

    assert declared_licence("anything") == expected


def test_run_as_a_script_it_prints_the_rows_and_exits_with_the_status(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["package_licenses.py", "pytest"])
    monkeypatch.delitem(sys.modules, "scripts.package_licenses")  # runpy warns about a module that is imported

    with pytest.raises(SystemExit) as raised:
        runpy.run_module("scripts.package_licenses", run_name="__main__")

    assert raised.value.code == 0
    assert capsys.readouterr().out.startswith("| pytest | ")
