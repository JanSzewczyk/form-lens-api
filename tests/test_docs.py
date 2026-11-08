"""Documentation that can drift from the code is checked here."""

import re
from pathlib import Path

from fastapi import FastAPI

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


def test_readme_lists_every_make_target() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8").replace("\\\n", " ")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    targets = [
        target
        for line in re.findall(r"^\.PHONY:(.*)$", makefile, re.MULTILINE)
        for target in line.split("#")[0].split()
    ]

    assert targets
    for target in targets:
        assert f"make {target}" in readme, target
