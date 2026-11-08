"""Checks that need the downloaded models: run them with `make test-models`.

They fail, not skip, when the files are missing: the point is to say the machine is not ready.
"""

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
