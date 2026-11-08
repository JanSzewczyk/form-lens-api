"""`scripts/resolve_model.py`: the one place that turns the settings into the model to download."""

import runpy
import sys
from pathlib import Path

import pytest
from pydantic import TypeAdapter, ValidationError

from formlens.modelspec import MODEL_SPECS
from scripts import resolve_model
from scripts.resolve_model import main, refusals

SCRIPT = Path(resolve_model.__file__)


@pytest.fixture(autouse=True)
def _empty_working_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Run from an empty folder: the settings read `.env` from the working directory, never the repository's."""
    monkeypatch.chdir(tmp_path)


def test_the_defaults_name_the_mlx_model_and_the_models_folder(capsys: pytest.CaptureFixture[str]) -> None:
    spec = MODEL_SPECS["mlx"]

    code = main([])

    assert code == 0
    assert capsys.readouterr().out.splitlines() == [spec.repo, spec.revision, spec.folder, "models"]


@pytest.mark.parametrize("backend", ["mlx", "transformers"])
def test_the_environment_selects_the_backend_and_the_path(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, backend: str
) -> None:
    spec = MODEL_SPECS[backend]  # type: ignore[index]  # the parameter is one of the two keys
    monkeypatch.setenv("VLM_BACKEND", backend)
    monkeypatch.setenv("MODELS_PATH", "nested/weights")

    code = main([])

    assert code == 0
    assert capsys.readouterr().out.splitlines() == [spec.repo, spec.revision, spec.folder, "nested/weights"]


def test_a_dot_env_in_the_working_directory_moves_the_resolution(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / ".env").write_text("VLM_BACKEND=transformers\nMODELS_PATH=from-file\n", encoding="utf-8")
    spec = MODEL_SPECS["transformers"]

    code = main([])

    assert code == 0
    assert capsys.readouterr().out.splitlines() == [spec.repo, spec.revision, spec.folder, "from-file"]


def test_the_environment_beats_the_dot_env(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / ".env").write_text("VLM_BACKEND=transformers\nMODELS_PATH=from-file\n", encoding="utf-8")
    monkeypatch.setenv("VLM_BACKEND", "mlx")
    monkeypatch.setenv("MODELS_PATH", "from-environment")
    spec = MODEL_SPECS["mlx"]

    code = main([])

    assert code == 0
    assert capsys.readouterr().out.splitlines() == [spec.repo, spec.revision, spec.folder, "from-environment"]


def test_an_unrelated_bad_value_in_the_dot_env_does_not_block_the_resolution(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / ".env").write_text("PORT=abc\nMAX_UPLOAD_MB=lots\n", encoding="utf-8")

    code = main([])

    assert code == 0
    assert capsys.readouterr().out.splitlines()[0] == MODEL_SPECS["mlx"].repo


def test_an_unknown_backend_is_refused_with_the_value_and_exit_3(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VLM_BACKEND", "cuda")

    code = main([])

    captured = capsys.readouterr()
    assert code == 3
    assert captured.out == ""
    assert captured.err == "VLM_BACKEND must be 'mlx' or 'transformers', not 'cuda'.\n"


def test_an_empty_models_path_is_refused_with_the_stage_0_message(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MODELS_PATH", "")

    code = main([])

    captured = capsys.readouterr()
    assert code == 3
    assert captured.out == ""
    assert captured.err == "MODELS_PATH must not be empty; unset it to use 'models'.\n"


def test_two_refused_settings_are_both_reported_the_backend_first(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MODELS_PATH", "")
    monkeypatch.setenv("VLM_BACKEND", "MLX")

    code = main([])

    assert code == 3
    assert capsys.readouterr().err.splitlines() == [
        "VLM_BACKEND must be 'mlx' or 'transformers', not 'MLX'.",
        "MODELS_PATH must not be empty; unset it to use 'models'.",
    ]


def test_a_path_with_a_line_break_is_refused_because_the_output_is_line_based(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MODELS_PATH", "a\nb")

    code = main([])

    captured = capsys.readouterr()
    assert code == 3
    assert captured.out == ""
    assert "line break" in captured.err


def test_a_refusal_the_script_has_no_text_for_still_names_the_setting_and_the_reason() -> None:
    with pytest.raises(ValidationError) as caught:
        TypeAdapter(int).validate_python("many")

    assert refusals(caught.value) == [
        "The settings is invalid: Input should be a valid integer, unable to parse string as an integer."
    ]


def test_an_argument_is_refused_by_the_parser(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as caught:
        main(["--unknown"])

    assert caught.value.code == 2
    assert "unrecognized arguments" in capsys.readouterr().err


def test_running_the_file_as_a_script_exits_with_the_code_of_main(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "argv", [str(SCRIPT)])
    monkeypatch.setenv("VLM_BACKEND", "cuda")

    with pytest.raises(SystemExit) as caught:
        runpy.run_path(str(SCRIPT), run_name="__main__")

    assert caught.value.code == 3
    assert "VLM_BACKEND" in capsys.readouterr().err
