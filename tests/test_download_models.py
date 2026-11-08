"""`scripts/download_models.sh` with a fake downloader: no network, no real model."""

import os
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest

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
