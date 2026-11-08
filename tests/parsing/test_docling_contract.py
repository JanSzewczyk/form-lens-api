"""What cannot be checked in the test process: Docling's real names and the promise not to import it.

Docling takes seconds to import and pulls in torch, so each check runs in a child interpreter. That
keeps this process free of both, which the other tests rely on, and `sys.modules` of the child is the
only honest evidence that a module was not imported.
"""

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from formlens.modelspec import MODEL_SPECS, VlmBackend

HEAVY = ["docling", "torch", "transformers", "mlx", "mlx_vlm", "PIL"]


def run_child(code: str, *, cwd: Path) -> dict[str, object]:
    """Run `code` in a fresh interpreter and return the JSON it prints on its last line."""
    done = subprocess.run(  # noqa: S603 - our own interpreter and our own code
        [sys.executable, "-I", "-c", textwrap.dedent(code)],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=50,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    return dict(json.loads(done.stdout.strip().splitlines()[-1]))


def test_importing_the_app_and_building_it_imports_neither_docling_nor_torch(tmp_path: Path) -> None:
    report = run_child(
        f"""
        import json, sys
        from formlens.config import Settings
        from formlens.main import create_app
        create_app(Settings(_env_file=None, environment="test"))
        print(json.dumps({{name: name in sys.modules for name in {HEAVY!r}}}))
        """,
        cwd=tmp_path,
    )

    assert report == dict.fromkeys(HEAVY, False)


def test_a_bogus_models_path_fails_with_model_unavailable_without_importing_docling(tmp_path: Path) -> None:
    report = run_child(
        f"""
        import json, os, sys
        from pathlib import Path
        from formlens.config import Settings
        from formlens.parsing.docling_parser import build_docling_parser
        from formlens.parsing.exceptions import ModelUnavailable
        settings = Settings(_env_file=None, environment="test", models_path=Path("/nonexistent/models"))
        try:
            build_docling_parser(settings)
        except ModelUnavailable as exc:
            raised = str(exc)
        else:
            raised = None
        print(json.dumps({{
            "raised": raised,
            "imported": [name for name in {HEAVY!r} if name in sys.modules],
            "offline_set": "HF_HUB_OFFLINE" in os.environ,
        }}))
        """,
        cwd=tmp_path,
    )

    assert report["imported"] == []
    assert report["offline_set"] is False  # nothing is switched before the check passes
    assert "ibm-granite/granite-docling-258M-mlx is incomplete in /nonexistent/models" in str(report["raised"])


@pytest.mark.parametrize("backend", ["mlx", "transformers"])
def test_the_pinned_repo_is_the_one_docling_resolves_for_its_granite_docling_preset(
    tmp_path: Path, backend: VlmBackend
) -> None:
    """`MODEL_SPECS` pins the revision; Docling's preset names only `main`, so only the repo can be compared."""
    engine = "MlxVlmEngineOptions" if backend == "mlx" else "TransformersVlmEngineOptions"
    kind = "MLX" if backend == "mlx" else "TRANSFORMERS"
    report = run_child(
        f"""
        import json
        from docling.datamodel.pipeline_options import VlmConvertOptions
        from docling.datamodel.vlm_engine_options import {engine}, VlmEngineType
        options = VlmConvertOptions.from_preset("granite_docling", engine_options={engine}())
        print(json.dumps({{"repo": options.model_spec.get_repo_id(VlmEngineType.{kind})}}))
        """,
        cwd=tmp_path,
    )

    assert report["repo"] == MODEL_SPECS[backend].repo
