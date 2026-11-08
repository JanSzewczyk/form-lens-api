"""Versions that are pinned in more than one file must say the same thing."""

import re
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
    }

    assert len(set(versions.values())) == 1, versions
