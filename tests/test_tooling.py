"""Versions that are pinned in more than one file must say the same thing."""

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def pinned(name: str, pattern: str) -> str:
    match = re.search(pattern, read(name), re.MULTILINE)
    assert match, f"{name} no longer pins uv in the form {pattern!r}"
    return match["version"]


def test_the_uv_version_is_the_same_in_the_dockerfile_and_ci() -> None:
    """Dependabot's docker ecosystem bumps only the Dockerfile, so drift shows up here."""
    versions = {
        "Dockerfile": pinned("Dockerfile", r"^FROM ghcr\.io/astral-sh/uv:(?P<version>[\d.]+) "),
        ".github/workflows/ci.yml": pinned(".github/workflows/ci.yml", r'^  UV_VERSION: "(?P<version>[\d.]+)"'),
        ".github/workflows/release.yml": pinned(
            ".github/workflows/release.yml", r'^  UV_VERSION: "(?P<version>[\d.]+)"'
        ),
    }

    assert len(set(versions.values())) == 1, versions


def test_the_adapter_contract_lists_every_module_that_must_not_import_the_adapter() -> None:
    """A source that contains the forbidden module finds nothing, so the contract lists modules one by one.

    A new module that is neither listed nor one of the two entry points would be free to import Docling.
    """
    contracts = tomllib.loads(read("pyproject.toml"))["tool"]["importlinter"]["contracts"]
    [contract] = [c for c in contracts if c.get("forbidden_modules") == ["formlens.parsing.docling_parser"]]
    package = ROOT / "src" / "formlens"
    units = set()
    for path in package.rglob("*.py"):
        parts = path.relative_to(package).with_suffix("").parts
        if parts[-1] == "__init__":
            parts = parts[:-1]
        if parts:  # the root package itself is not a module to list
            units.add("formlens." + ".".join(parts[:2] if parts[0] == "parsing" else parts[:1]))
    left_out = {"formlens.main", "formlens.__main__", "formlens.parsing", "formlens.parsing.docling_parser"}

    assert units - left_out == set(contract["source_modules"])
