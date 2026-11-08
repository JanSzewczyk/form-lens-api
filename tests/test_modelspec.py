"""The pinned model specs: the shape every reader of them relies on."""

import dataclasses
import re
import subprocess
import sys
from typing import get_args

import pytest

from formlens.modelspec import MODEL_SPECS, ModelSpec, VlmBackend


def test_every_backend_has_a_spec_and_nothing_else_does() -> None:
    assert set(MODEL_SPECS) == set(get_args(VlmBackend.__value__))


@pytest.mark.parametrize("backend", sorted(MODEL_SPECS), ids=sorted(MODEL_SPECS))
def test_a_spec_pins_a_full_commit_hash_of_an_owner_and_repository(backend: VlmBackend) -> None:
    spec = MODEL_SPECS[backend]

    assert re.fullmatch(r"[0-9a-f]{40}", spec.revision)
    assert re.fullmatch(r"[\w.-]+/[\w.-]+", spec.repo)


@pytest.mark.parametrize("backend", sorted(MODEL_SPECS), ids=sorted(MODEL_SPECS))
def test_the_files_include_the_weights_and_the_config_the_service_loads(backend: VlmBackend) -> None:
    files = MODEL_SPECS[backend].files

    assert {"config.json", "model.safetensors", "tokenizer.json"} <= set(files)
    assert len(files) == len(set(files))


def test_the_folder_is_the_repository_with_a_double_dash_for_the_slash() -> None:
    assert ModelSpec(repo="owner/name", revision="0" * 40, files=()).folder == "owner--name"
    assert MODEL_SPECS["mlx"].folder == "ibm-granite--granite-docling-258M-mlx"


def test_the_two_backends_do_not_share_a_folder_or_a_revision() -> None:
    mlx, transformers = MODEL_SPECS["mlx"], MODEL_SPECS["transformers"]

    assert mlx.folder != transformers.folder
    assert mlx.revision != transformers.revision


def test_a_spec_cannot_be_changed() -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        MODEL_SPECS["mlx"].revision = "0" * 40  # type: ignore[misc]  # the point of the test


def test_the_module_needs_only_the_standard_library() -> None:
    """The downloader imports it through the project's package, so it must stay cheap and dependency-free."""
    heavy = ("fastapi", "pydantic", "torch", "docling")
    code = f"import sys, formlens.modelspec; print(sorted(m for m in {heavy!r} if m in sys.modules))"

    result = subprocess.run(  # noqa: S603  # this interpreter, fixed arguments
        [sys.executable, "-c", code], capture_output=True, text=True, check=False, timeout=30
    )

    assert result.stdout.strip() == "[]", result.stderr
