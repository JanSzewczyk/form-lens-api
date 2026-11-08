"""Checks that need the downloaded models: run them with `make test-models`.

They fail, not skip, when the files are missing: the point is to say the machine is not ready.
"""

import os
import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

from formlens.config import Settings
from tests.model_pins import MODEL_PINS


@pytest.mark.slow
@pytest.mark.timeout(600)
def test_the_pinned_model_files_are_present_under_the_models_path() -> None:
    settings = Settings(_env_file=None)  # MODELS_PATH and VLM_BACKEND from the environment, not .env
    pin = MODEL_PINS[settings.vlm_backend]
    folder = settings.models_path / pin.folder
    hint = f"{pin.repo} is not in {folder}; run `make download-models`"

    assert folder.is_dir(), hint
    assert (folder / ".revision").is_file(), hint
    assert (folder / ".revision").read_text(encoding="utf-8").strip() == pin.revision, hint
    assert [name for name in pin.files if not (folder / name).is_file()] == [], hint
    assert (folder / "model.safetensors").stat().st_size > 100_000_000, "model.safetensors looks truncated"


# --- Stage 0 contract tests: the `slow` test fails clearly, and `make check` never reaches it -----

ROOT = Path(__file__).resolve().parent.parent
THIS_FILE = "tests/test_models.py"


def run_pytest(
    *arguments: str, models_path: Path | None = None, backend: str = "mlx"
) -> subprocess.CompletedProcess[str]:
    """Run pytest on this file in a child process, as `make test-models` does, against another models folder."""
    environment = {key: value for key, value in os.environ.items() if key not in {"MODELS_PATH", "VLM_BACKEND"}}
    environment["VLM_BACKEND"] = backend
    if models_path is not None:
        environment["MODELS_PATH"] = str(models_path)
    return subprocess.run(  # noqa: S603  # this interpreter, fixed arguments
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-p", "no:randomly", *arguments],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )


def lay_out_the_model(models_path: Path, backend: str = "mlx") -> Path:
    """Create the files the slow test looks for; `model.safetensors` is sparse, so it costs no disk."""
    pin = MODEL_PINS[backend]
    folder = models_path / pin.folder
    folder.mkdir(parents=True)
    for name in pin.files:
        (folder / name).write_text("{}", encoding="utf-8")
    with (folder / "model.safetensors").open("wb") as weights:
        weights.truncate(100_000_001)
    (folder / ".revision").write_text(pin.revision + "\n", encoding="utf-8")
    return folder


def test_the_default_run_does_not_collect_the_slow_test_so_check_needs_no_models(tmp_path: Path) -> None:
    """`make check` runs plain pytest: with no models at all it must still be green."""
    result = run_pytest(THIS_FILE, "--collect-only", "-q", models_path=tmp_path / "absent")

    assert result.returncode == 0, result.stdout
    assert "test_the_pinned_model_files_are_present_under_the_models_path" not in result.stdout
    assert "test_the_slow_test_follows_the_backend_setting" in result.stdout
    assert not (tmp_path / "absent").exists()


def test_only_make_test_models_overrides_the_default_deselection_of_the_slow_tests() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    recipes = dict(re.findall(r"^([a-z][a-z-]*):[^\n]*\n((?:\t[^\n]*\n)+)", makefile, re.MULTILINE))

    assert "test-models" in recipes
    assert [name for name, recipe in recipes.items() if "-m slow" in recipe] == ["test-models"]
    assert "pytest -m slow tests/test_models.py" in recipes["test-models"]


def test_make_test_models_fails_with_a_hint_when_the_models_are_absent(tmp_path: Path) -> None:
    """The one run through a child pytest, with the command `make test-models` uses."""
    result = run_pytest("-m", "slow", THIS_FILE, models_path=tmp_path / "absent")

    assert result.returncode == 1
    assert "make download-models" in result.stdout
    assert str(tmp_path / "absent") in result.stdout  # MODELS_PATH from the environment reached the test
    assert "1 failed" in result.stdout


def test_the_slow_test_passes_when_the_pinned_files_are_in_place(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lay_out_the_model(tmp_path / "models")
    monkeypatch.setenv("MODELS_PATH", str(tmp_path / "models"))
    monkeypatch.delenv("VLM_BACKEND", raising=False)

    test_the_pinned_model_files_are_present_under_the_models_path()


def test_the_slow_test_follows_the_backend_setting(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    lay_out_the_model(tmp_path / "models", "mlx")
    monkeypatch.setenv("MODELS_PATH", str(tmp_path / "models"))
    monkeypatch.setenv("VLM_BACKEND", "transformers")

    with pytest.raises(AssertionError, match=r"granite-docling-258M is not in .*make download-models"):
        test_the_pinned_model_files_are_present_under_the_models_path()


def set_a_wrong_revision(folder: Path) -> None:
    (folder / ".revision").write_text("0" * 40 + "\n", encoding="utf-8")


def delete_the_tokenizer(folder: Path) -> None:
    (folder / "tokenizer.json").unlink()


def cut_the_weights_short(folder: Path) -> None:
    (folder / "model.safetensors").write_bytes(b"x" * 1000)


def delete_the_marker(folder: Path) -> None:
    (folder / ".revision").unlink()


@pytest.mark.parametrize(
    ("damage", "message"),
    [
        pytest.param(set_a_wrong_revision, "make download-models", id="wrong-revision"),
        pytest.param(delete_the_tokenizer, "make download-models", id="missing-file"),
        pytest.param(cut_the_weights_short, "looks truncated", id="truncated-weights"),
        pytest.param(delete_the_marker, "make download-models", id="no-marker"),
    ],
)
def test_the_slow_test_fails_for_each_way_a_download_can_be_wrong(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, damage: Callable[[Path], None], message: str
) -> None:
    damage(lay_out_the_model(tmp_path / "models"))
    monkeypatch.setenv("MODELS_PATH", str(tmp_path / "models"))
    monkeypatch.delenv("VLM_BACKEND", raising=False)

    with pytest.raises(AssertionError, match=message):
        test_the_pinned_model_files_are_present_under_the_models_path()
