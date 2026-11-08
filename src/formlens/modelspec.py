"""The pinned document models: the one place that names a repository, a revision and the files.

The service, `scripts/resolve_model.py` (which `make download-models` runs) and the tests all read
these values. Bump a revision here and in `docs/licenses.md` together; `tests/test_docs.py` fails
until they agree. Standard library only, so the downloader script can import it cheaply.
"""

from dataclasses import dataclass
from typing import Final, Literal

type VlmBackend = Literal["mlx", "transformers"]


@dataclass(frozen=True, slots=True)
class ModelSpec:
    """One downloadable model: its Hugging Face repository, revision and the files the service needs."""

    repo: str
    revision: str
    files: tuple[str, ...]

    @property
    def folder(self) -> str:
        """Return the folder name under the models path, the one Docling expects for `artifacts_path`."""
        return self.repo.replace("/", "--")


_MODEL_FILES: Final = (
    "config.json",
    "model.safetensors",
    "tokenizer.json",
    "tokenizer_config.json",
    "preprocessor_config.json",
    "processor_config.json",
    "chat_template.jinja",
)

MODEL_SPECS: Final[dict[VlmBackend, ModelSpec]] = {
    "mlx": ModelSpec(
        repo="ibm-granite/granite-docling-258M-mlx",
        revision="e9939db25d2f296c8678d0491c4609a8c596c50a",
        files=_MODEL_FILES,
    ),
    "transformers": ModelSpec(
        repo="ibm-granite/granite-docling-258M",
        revision="982fe3b40f2fa73c365bdb1bcacf6c81b7184bfe",
        files=_MODEL_FILES,
    ),
}
