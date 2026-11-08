"""Documentation that can drift from the code is checked here."""

import re
from pathlib import Path

import pytest
from fastapi import FastAPI

from formlens.modelspec import MODEL_SPECS, VlmBackend

ROOT = Path(__file__).resolve().parent.parent


def test_every_problem_type_is_in_the_reference(app: FastAPI) -> None:
    reference = (ROOT / "docs" / "reference" / "problem-types.md").read_text(encoding="utf-8")

    assert app.state.problem_types
    for kind in app.state.problem_types:
        assert f"`{kind.slug}`" in reference, kind.slug
        assert f"| {kind.status} |" in reference, kind.slug


def test_every_problem_type_in_the_reference_is_registered(app: FastAPI) -> None:
    """The reverse of the test above: a row left behind after its type was removed fails here."""
    reference = (ROOT / "docs" / "reference" / "problem-types.md").read_text(encoding="utf-8")
    rows = re.findall(r"^\| `([a-z0-9-]+)` \| (\d{3}) \| ([^|]+?) \|", reference, re.MULTILINE)
    registered = {kind.slug: (str(kind.status), kind.title) for kind in app.state.problem_types}

    assert rows
    documented = {slug: (status, title) for slug, status, title in rows}
    assert documented == registered


@pytest.mark.parametrize("backend", sorted(MODEL_SPECS), ids=sorted(MODEL_SPECS))
def test_licenses_state_the_pinned_model(backend: VlmBackend) -> None:
    """`modelspec.py` is the one place with the pins; `docs/licenses.md` is the tripwire that repeats them."""
    spec = MODEL_SPECS[backend]
    licenses = (ROOT / "docs" / "licenses.md").read_text(encoding="utf-8")

    assert f"| `{backend}` | [{spec.repo}]" in licenses
    assert f"`{spec.revision}`" in licenses


def test_the_download_script_holds_no_pin_of_its_own() -> None:
    """A repository or revision written into the script would be a second source that can drift."""
    script = (ROOT / "scripts" / "download_models.sh").read_text(encoding="utf-8")

    for spec in MODEL_SPECS.values():
        assert spec.revision not in script
        assert spec.repo not in script


def test_readme_names_every_make_target_as_a_whole_word() -> None:
    """`make test` is a prefix of `make test-models`, so each target is matched as a whole word."""
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    targets = re.findall(r"^([a-z][a-z-]*):", makefile, re.MULTILINE)

    assert "test-models" in targets
    missing = [t for t in targets if not re.search(rf"\bmake {re.escape(t)}(?![\w-])", readme)]
    assert missing == []


def test_every_make_target_is_declared_phony() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    joined = makefile.replace("\\\n", " ")
    declared = {t for line in re.findall(r"^\.PHONY:(.*)$", joined, re.MULTILINE) for t in line.split()}
    rules = set(re.findall(r"^([a-z][a-z-]*):", makefile, re.MULTILINE))

    assert rules == declared
