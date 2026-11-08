"""`scripts/download_models.sh` with a fake downloader: no network, no real model."""

import os
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
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
mkdir -p "$target"
echo '{}' > "$target/config.json"
"""


@dataclass(frozen=True)
class Run:
    """Outcome of one script run."""

    process: subprocess.CompletedProcess[str]
    models: Path
    calls: list[str]


type RunScript = Callable[..., Run]


@pytest.fixture
def run_script(tmp_path: Path) -> RunScript:
    """Return a function that runs the script against one models folder and the fake downloader."""
    downloader = tmp_path / "fake-hf"
    downloader.write_text(FAKE_DOWNLOADER, encoding="utf-8")
    downloader.chmod(0o755)
    models = tmp_path / "models"
    log = tmp_path / "calls.log"

    def run(*, backend: str | None = None, fail: bool = False) -> Run:
        env = {
            "PATH": os.environ["PATH"],
            "HF_CLI": str(downloader),
            "MODELS_PATH": str(models),
            "FAKE_HF_LOG": str(log),
        }
        if backend is not None:
            env["VLM_BACKEND"] = backend
        if fail:
            env["FAKE_HF_FAIL"] = "1"
        process = subprocess.run(  # noqa: S603  # the script under test, with a fixed argument list
            [str(SCRIPT)], env=env, capture_output=True, text=True, check=False, timeout=30
        )
        calls = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
        return Run(process=process, models=models, calls=calls)

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


# --- Stage 0 contract tests: invalid input, the downloader override, the marker, parity ----------


def make_script_tree(root: Path) -> Path:
    """Copy the script into `root/scripts/`, so its `cd ..` lands in `root` and the repository is untouched."""
    copy = root / "scripts" / "download_models.sh"
    copy.parent.mkdir(parents=True)
    copy.write_bytes(SCRIPT.read_bytes())
    copy.chmod(0o755)
    return copy


def write_fake_downloader(path: Path) -> Path:
    path.write_text(FAKE_DOWNLOADER, encoding="utf-8")
    path.chmod(0o755)
    return path


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


def test_make_passes_the_backend_variable_to_the_script_and_refuses_an_unknown_one() -> None:
    """`make download-models VLM_BACKEND=cuda` is the documented form; it must stop before any download."""
    result = subprocess.run(  # fixed arguments; no network is reached
        ["make", "-s", "download-models", "VLM_BACKEND=cuda", "HF_CLI=/nonexistent/downloader"],  # noqa: S607
        cwd=SCRIPT.parent.parent,
        env={"PATH": os.environ["PATH"]},
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )

    assert result.returncode != 0
    assert "VLM_BACKEND must be 'mlx' or 'transformers', not 'cuda'" in result.stderr


def test_a_missing_downloader_is_a_clear_error_and_creates_nothing(tmp_path: Path) -> None:
    script = make_script_tree(tmp_path)
    environment = {"PATH": os.environ["PATH"], "HF_CLI": "no-such-downloader-4f7a", "MODELS_PATH": str(tmp_path / "m")}

    process = subprocess.run(  # noqa: S603  # the script under test
        [str(script)], env=environment, capture_output=True, text=True, check=False, timeout=30
    )

    assert process.returncode == 1
    assert "'no-such-downloader-4f7a' not found" in process.stderr
    assert "HF_CLI" in process.stderr
    assert not (tmp_path / "m").exists()


def test_the_downloader_override_may_carry_arguments(tmp_path: Path) -> None:
    script = make_script_tree(tmp_path)
    downloader = write_fake_downloader(tmp_path / "fake-hf")
    log = tmp_path / "calls.log"
    pin = MODEL_PINS["mlx"]
    environment = {
        "PATH": os.environ["PATH"],
        "HF_CLI": f"{downloader} --profile offline",
        "MODELS_PATH": str(tmp_path / "m"),
        "FAKE_HF_LOG": str(log),
    }

    process = subprocess.run(  # noqa: S603  # the script under test
        [str(script)], env=environment, capture_output=True, text=True, check=False, timeout=30
    )

    folder = tmp_path / "m" / pin.folder
    assert process.returncode == 0, process.stderr
    assert log.read_text(encoding="utf-8").splitlines() == [
        f"--profile offline download {pin.repo} --revision {pin.revision} --local-dir {folder}"
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


def test_a_relative_models_path_lands_where_the_service_reads_it(tmp_path: Path) -> None:
    """Two documented rules disagree.

    The script header and README say a relative `MODELS_PATH` is read from the repository root.
    `.env.example`, the README settings table and `Settings.models_path` say it is read from the
    working directory. Run from anywhere but the root, the model lands where the service will not
    look. The script runs from a copy in `tmp_path`, so the real repository is not written to.
    """
    script = make_script_tree(tmp_path)
    downloader = write_fake_downloader(tmp_path / "fake-hf")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    pin = MODEL_PINS["mlx"]
    environment = {
        "PATH": os.environ["PATH"],
        "HF_CLI": str(downloader),
        "MODELS_PATH": "weights",
        "FAKE_HF_LOG": str(tmp_path / "calls.log"),
    }

    process = subprocess.run(  # noqa: S603  # the script under test
        [str(script)], cwd=elsewhere, env=environment, capture_output=True, text=True, check=False, timeout=30
    )

    assert process.returncode == 0, process.stderr
    service_reads = elsewhere / Settings(_env_file=None, models_path=Path("weights")).models_path / pin.folder
    assert (service_reads / ".revision").is_file()


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
    """A value one of them takes and the other refuses means a download the service cannot use.

    An exported empty `VLM_BACKEND=` (a shell `export VLM_BACKEND=` or a CI variable that renders empty) is
    read by the script as "not set" (`${VLM_BACKEND:-mlx}`) and downloads the mlx model, while the settings
    refuse it and the service will not start. Either make the script reject an empty value or set
    `env_ignore_empty=True` on the settings; no source says which is meant.
    """
    settings_accept = settings_accept_backend(backend, monkeypatch)

    script_accepts = run_script(backend=backend).process.returncode == 0

    assert script_accepts == settings_accept
