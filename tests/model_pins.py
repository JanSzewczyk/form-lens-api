"""The model revisions the service is pinned to, written out a second time on purpose.

`scripts/download_models.sh` and `docs/licenses.md` state the same values; the tests compare them,
so changing a pin in one place fails until the others follow.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelPin:
    """One downloadable model: its Hugging Face repo, revision and the files the service needs."""

    repo: str
    revision: str
    files: tuple[str, ...]

    @property
    def folder(self) -> str:
        """Folder name under the models path; the one Docling expects for `artifacts_path`."""
        return self.repo.replace("/", "--")


_MODEL_FILES = (
    "config.json",
    "model.safetensors",
    "tokenizer.json",
    "tokenizer_config.json",
    "preprocessor_config.json",
    "processor_config.json",
    "chat_template.jinja",
)

MODEL_PINS: dict[str, ModelPin] = {
    "mlx": ModelPin(
        repo="ibm-granite/granite-docling-258M-mlx",
        revision="e9939db25d2f296c8678d0491c4609a8c596c50a",
        files=_MODEL_FILES,
    ),
    "transformers": ModelPin(
        repo="ibm-granite/granite-docling-258M",
        revision="982fe3b40f2fa73c365bdb1bcacf6c81b7184bfe",
        files=_MODEL_FILES,
    ),
}
