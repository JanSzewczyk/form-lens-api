"""The service makes no outbound connection: not when it loads the model and not when it parses.

The check runs in a child interpreter (`tests/offline_child.py`) because `HF_HUB_OFFLINE` is read when
`huggingface_hub` is imported. The child blocks and records every connect and name lookup before it
imports anything, then loads the real model and parses a PDF and a PNG. The parent asserts on the
recorded attempts, not on stderr: importing torch prints a line there on macOS.
"""

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from tests.conftest import slow_settings

CHILD = Path(__file__).resolve().parent.parent / "offline_child.py"


def run_child(mode: str, tmp_path: Path, *, models_path: Path | None = None, backend: str = "mlx") -> dict[str, Any]:
    """Run the child in `mode` and return its report; the child must exit 0."""
    report = tmp_path / "report.json"
    environment = {key: value for key, value in os.environ.items() if key != "HF_HUB_OFFLINE"}
    if models_path is not None:
        environment.update(MODELS_PATH=str(models_path), VLM_BACKEND=backend)
    done = subprocess.run(  # noqa: S603  # this interpreter and our own script
        [sys.executable, "-I", str(CHILD), mode, str(report)],
        cwd=tmp_path,  # no `.env` to read
        env=environment,
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    assert done.returncode == 0, done.stderr[-3000:]
    return dict(json.loads(report.read_text(encoding="utf-8")))


def test_the_guard_records_a_connect_a_create_connection_and_a_name_lookup(tmp_path: Path) -> None:
    """The offline test below is worth something only if the guard can see an attempt."""
    report = run_child("probe", tmp_path)

    assert [attempt["call"] for attempt in report["attempts"]] == ["connect", "create_connection", "getaddrinfo"]
    assert "127.0.0.1" in report["attempts"][0]["arguments"]
    assert "example.invalid" in report["attempts"][2]["arguments"]


@pytest.mark.slow
@pytest.mark.timeout(600)
def test_loading_the_model_and_parsing_a_pdf_and_a_png_make_no_network_attempt(tmp_path: Path) -> None:
    settings = slow_settings()

    report = run_child("parse", tmp_path, models_path=settings.models_path, backend=settings.vlm_backend)

    assert report["attempts"] == []
    assert report["hf_hub_offline"] == "1"  # the adapter switched it on before importing Docling
    assert [(item["file"], item["status"]) for item in report["responses"]] == [
        ("text_layer.pdf", 200),
        ("sample.png", 200),
    ]
    assert all(item["page_count"] == 1 and item["text"].strip() for item in report["responses"])
