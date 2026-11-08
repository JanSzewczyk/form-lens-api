"""`scripts/download_models.sh` with a fake downloader: no network, no real model."""

import os
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import pytest
from pydantic import ValidationError

from formlens.config import Settings
from tests.model_pins import MODEL_PINS

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "download_models.sh"

FAKE_DOWNLOADER = """\
#!/usr/bin/env bash
# Records its arguments and creates the files a real download would leave in --local-dir.
printf '%s\\n' "$*" >> "$FAKE_HF_LOG"
if [ -n "${FAKE_HF_FAIL:-}" ]; then
    echo "network unreachable" >&2
    exit 1
fi
target="${@: -1}"
mkdir -p -- "$target"
echo '{}' > "$target/config.json"
"""


class Use(Enum):
    """What `run_script` does with a variable the test does not set to a text."""

    DEFAULT = "the default of the fixture"
    UNSET = "leave the variable out of the environment"


@dataclass(frozen=True)
class Run:
    """Outcome of one script run."""

    process: subprocess.CompletedProcess[str]
    models: Path
    calls: list[str]
    cwd: Path


type RunScript = Callable[..., Run]


@pytest.fixture
def fake_downloader(tmp_path: Path) -> Path:
    """The path of a downloader that records its arguments in `$FAKE_HF_LOG` and creates the model files."""
    downloader = tmp_path / "fake-hf"
    downloader.write_text(FAKE_DOWNLOADER, encoding="utf-8")
    downloader.chmod(0o755)
    return downloader


@pytest.fixture
def run_script(tmp_path: Path, fake_downloader: Path) -> RunScript:
    """Return a function that runs the script from an empty working directory, with the fake downloader.

    `models` is the absolute folder the script writes to unless `models_path` says otherwise. Every run
    starts in `tmp_path / "cwd"`, so a relative `MODELS_PATH` never lands in the repository.
    """
    models = tmp_path / "models"
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    log = tmp_path / "calls.log"

    def run(
        *,
        backend: str | None = None,
        fail: bool = False,
        models_path: str | Use = Use.DEFAULT,
        hf_cli: str | None = None,
    ) -> Run:
        env = {
            "PATH": os.environ["PATH"],
            "HF_CLI": str(fake_downloader) if hf_cli is None else hf_cli,
            "FAKE_HF_LOG": str(log),
        }
        if models_path is Use.DEFAULT:
            env["MODELS_PATH"] = str(models)
        elif isinstance(models_path, str):
            env["MODELS_PATH"] = models_path
        if backend is not None:
            env["VLM_BACKEND"] = backend
        if fail:
            env["FAKE_HF_FAIL"] = "1"
        process = subprocess.run(  # noqa: S603  # the script under test, with a fixed argument list
            [str(SCRIPT)], cwd=cwd, env=env, capture_output=True, text=True, check=False, timeout=30
        )
        calls = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
        return Run(process=process, models=models, calls=calls, cwd=cwd)

    return run


@pytest.mark.parametrize("backend", ["mlx", "transformers"])
def test_the_pinned_revision_of_the_backend_is_downloaded_into_its_folder(run_script: RunScript, backend: str) -> None:
    pin = MODEL_PINS[backend]

    result = run_script(backend=backend)

    folder = result.models / pin.folder
    assert result.process.returncode == 0, result.process.stderr
    assert result.calls == [f"download {pin.repo} --revision {pin.revision} --local-dir {folder}"]
    assert (folder / ".revision").read_text(encoding="utf-8").strip() == pin.revision
    assert pin.revision in result.process.stdout


def test_the_mlx_model_is_the_default_backend(run_script: RunScript) -> None:
    pin = MODEL_PINS["mlx"]

    result = run_script()

    assert result.calls == [f"download {pin.repo} --revision {pin.revision} --local-dir {result.models / pin.folder}"]


def test_an_unknown_backend_is_rejected_before_anything_is_downloaded(run_script: RunScript) -> None:
    result = run_script(backend="cuda")

    assert result.process.returncode != 0
    assert "VLM_BACKEND must be 'mlx' or 'transformers'" in result.process.stderr
    assert result.calls == []
    assert not result.models.exists()


def test_a_model_already_at_the_pinned_revision_is_not_downloaded_again(run_script: RunScript) -> None:
    run_script()

    second = run_script()

    assert second.process.returncode == 0, second.process.stderr
    assert len(second.calls) == 1  # still only the first run's call
    assert "nothing to download" in second.process.stdout


def test_a_model_at_another_revision_is_downloaded_again(run_script: RunScript) -> None:
    pin = MODEL_PINS["mlx"]
    first = run_script()
    (first.models / pin.folder / ".revision").write_text("0" * 40 + "\n", encoding="utf-8")

    second = run_script()

    assert len(second.calls) == 2
    assert (second.models / pin.folder / ".revision").read_text(encoding="utf-8").strip() == pin.revision


def test_a_failed_download_leaves_no_revision_marker(run_script: RunScript) -> None:
    pin = MODEL_PINS["mlx"]

    result = run_script(fail=True)

    assert result.process.returncode != 0
    assert not (result.models / pin.folder / ".revision").exists()
    assert "Done" not in result.process.stdout


# --- invalid input, the downloader override, the marker, parity with the settings ------------------


@pytest.mark.parametrize(
    "backend",
    ["MLX", "Transformers", "cuda", "mlx ", " mlx", "mlx\nx", "../outside", "mlx/../..", "*"],
    ids=[
        "upper-mlx",
        "capitalised",
        "unknown",
        "trailing-space",
        "leading-space",
        "newline",
        "traversal",
        "dots",
        "glob",
    ],
)
def test_only_the_two_exact_backend_names_are_accepted(run_script: RunScript, backend: str) -> None:
    result = run_script(backend=backend)

    assert result.process.returncode == 2
    assert "VLM_BACKEND must be 'mlx' or 'transformers'" in result.process.stderr
    assert result.calls == []
    assert not result.models.exists()


@pytest.mark.parametrize(
    ("argument", "message"),
    [
        ("VLM_BACKEND=cuda", "VLM_BACKEND must be 'mlx' or 'transformers', not 'cuda'"),
        ("MODELS_PATH=", "MODELS_PATH must not be empty"),
    ],
    ids=["unknown-backend", "empty-models-path"],
)
def test_make_passes_its_variables_to_the_script_and_refuses_a_bad_one(argument: str, message: str) -> None:
    """`make download-models VLM_BACKEND=…` is the documented form; a bad value stops it before any download."""
    result = subprocess.run(  # noqa: S603  # fixed arguments; no network is reached
        ["make", "-s", "download-models", argument, "HF_CLI=/nonexistent/downloader"],  # noqa: S607
        cwd=SCRIPT.parent.parent,
        env={"PATH": os.environ["PATH"]},
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )

    assert result.returncode == 2
    assert message in result.stderr


def test_a_missing_downloader_is_a_clear_error_and_creates_nothing(run_script: RunScript) -> None:
    result = run_script(hf_cli="no-such-downloader-4f7a")

    assert result.process.returncode == 1
    assert "'no-such-downloader-4f7a' not found" in result.process.stderr
    assert "HF_CLI" in result.process.stderr
    assert not result.models.exists()


@pytest.mark.parametrize("hf_cli", [" ", "   ", "\t"], ids=["one-space", "spaces", "tab"])
def test_a_downloader_command_of_only_blanks_is_a_clear_error_and_creates_nothing(
    run_script: RunScript, hf_cli: str
) -> None:
    """Bash 3.2 (macOS) reports `HF[0]: unbound variable` for an empty array; the script says what is wrong."""
    result = run_script(hf_cli=hf_cli)

    assert result.process.returncode == 1
    assert "HF_CLI is empty or only spaces" in result.process.stderr
    assert "unbound" not in result.process.stderr
    assert result.calls == []
    assert not result.models.exists()


def test_the_downloader_override_may_carry_arguments(run_script: RunScript, fake_downloader: Path) -> None:
    pin = MODEL_PINS["mlx"]

    result = run_script(hf_cli=f"{fake_downloader} --profile offline")

    assert result.process.returncode == 0, result.process.stderr
    assert result.calls == [
        f"--profile offline download {pin.repo} --revision {pin.revision} --local-dir {result.models / pin.folder}"
    ]


def test_a_marker_without_the_model_files_is_not_taken_for_a_finished_download(run_script: RunScript) -> None:
    pin = MODEL_PINS["mlx"]
    first = run_script()
    (first.models / pin.folder / "config.json").unlink()

    second = run_script()

    assert len(second.calls) == 2
    assert (second.models / pin.folder / "config.json").is_file()


def test_each_backend_keeps_its_own_folder_and_marker(run_script: RunScript) -> None:
    mlx, transformers = MODEL_PINS["mlx"], MODEL_PINS["transformers"]
    run_script(backend="mlx")

    second = run_script(backend="transformers")
    third = run_script(backend="mlx")

    assert len(second.calls) == 2  # the first backend's model does not satisfy the second
    assert len(third.calls) == 2  # and the second does not disturb the first
    assert (third.models / mlx.folder / ".revision").read_text(encoding="utf-8").strip() == mlx.revision
    assert (third.models / transformers.folder / ".revision").read_text(
        encoding="utf-8"
    ).strip() == transformers.revision


def test_a_failed_download_over_an_older_revision_removes_the_old_marker(run_script: RunScript) -> None:
    """The marker says "this folder holds the pinned revision"; a download that died half way voids it."""
    pin = MODEL_PINS["mlx"]
    first = run_script()
    marker = first.models / pin.folder / ".revision"
    marker.write_text("0" * 40 + "\n", encoding="utf-8")

    failed = run_script(fail=True)

    assert failed.process.returncode != 0
    assert not marker.exists()


def test_an_empty_models_path_is_refused_and_nothing_is_written(run_script: RunScript) -> None:
    result = run_script(models_path="")

    assert result.process.returncode == 2
    assert "MODELS_PATH must not be empty" in result.process.stderr
    assert result.calls == []
    assert list(result.cwd.iterdir()) == []
    assert not result.models.exists()


def test_a_models_path_that_starts_with_a_dash_is_a_folder_and_not_an_option(run_script: RunScript) -> None:
    pin = MODEL_PINS["mlx"]

    result = run_script(models_path="-x")

    assert result.process.returncode == 0, result.process.stderr
    assert (result.cwd / "-x" / pin.folder / ".revision").read_text(encoding="utf-8").strip() == pin.revision
    assert result.calls == [f"download {pin.repo} --revision {pin.revision} --local-dir ./-x/{pin.folder}"]


def settings_folders(value: str | None, monkeypatch: pytest.MonkeyPatch, cwd: Path) -> list[Path]:
    """Where the service looks for the model with `MODELS_PATH=value` (unset for None), or [] if it refuses to start."""
    if value is not None:
        monkeypatch.setenv("MODELS_PATH", value)
    try:
        settings = Settings(_env_file=None)
    except ValidationError:
        return []
    return [cwd / settings.models_path / MODEL_PINS["mlx"].folder]


@pytest.mark.parametrize(
    "models_path",
    [None, "weights", "nested/weights", "-x", ""],
    ids=["unset", "relative", "nested", "leading-dash", "empty"],
)
def test_the_script_downloads_to_the_folder_the_settings_read(
    run_script: RunScript, monkeypatch: pytest.MonkeyPatch, models_path: str | None
) -> None:
    """Both are run from the same working directory with the same `MODELS_PATH`.

    A value the settings refuse must be refused by the script too, and every other value must give the same
    folder, so a model is never downloaded to a place the service does not read.
    """
    run = run_script(models_path=Use.UNSET if models_path is None else models_path)

    downloaded = sorted(marker.parent for marker in run.cwd.rglob(".revision"))

    assert downloaded == settings_folders(models_path, monkeypatch, run.cwd)


def settings_accept_backend(backend: str, monkeypatch: pytest.MonkeyPatch) -> bool:
    monkeypatch.setenv("VLM_BACKEND", backend)
    try:
        Settings(_env_file=None)
    except ValidationError:
        return False
    return True


@pytest.mark.parametrize(
    "backend",
    ["mlx", "transformers", "cuda", "MLX", ""],
    ids=["mlx", "transformers", "unknown", "wrong-case", "empty"],
)
def test_the_script_and_the_settings_accept_the_same_backend_names(
    run_script: RunScript, monkeypatch: pytest.MonkeyPatch, backend: str
) -> None:
    """A name one of them takes and the other refuses means a download the service cannot use.

    An exported empty `VLM_BACKEND=` (a shell `export VLM_BACKEND=` or a CI variable that renders empty)
    is refused by both.
    """
    settings_accept = settings_accept_backend(backend, monkeypatch)

    script_accepts = run_script(backend=backend).process.returncode == 0

    assert script_accepts == settings_accept
