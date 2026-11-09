"""The Docling adapter: the one module that imports Docling, and only inside `build_docling_parser`.

Importing Docling takes seconds and pulls in torch, so `import formlens.main` must not do it: the
tests, the OpenAPI export and every other import stay light, and the model is loaded once, at startup.
"""

import os
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Final, Protocol

import structlog

from formlens.config import Settings
from formlens.modelspec import MODEL_SPECS
from formlens.parsing.exceptions import InvalidFile, ModelUnavailable, ParseFailed
from formlens.parsing.models import BYTES_PER_MB
from formlens.parsing.ports import ParseResult

_SUCCESS: Final = "success"  # `ConversionStatus.SUCCESS`, a `str` enum; compared by value so no import is needed
_FALLBACK_NAME: Final = "upload"

log = structlog.get_logger(__name__)


class ConversionIncomplete(RuntimeError):
    """Docling returned a result that is not a success; `status` is its status value."""

    def __init__(self, status: str) -> None:
        """Keep the status value for the failure that is logged."""
        self.status = status
        super().__init__(f"conversion ended with status {status}")


class _Input(Protocol):
    @property
    def valid(self) -> bool: ...
    @property
    def page_count(self) -> int: ...


class _Document(Protocol):
    def export_to_markdown(self) -> str: ...
    def export_to_text(self) -> str: ...


class _Result(Protocol):
    @property
    def status(self) -> str: ...
    @property
    def input(self) -> _Input: ...
    @property
    def document(self) -> _Document: ...


class _Converter(Protocol):
    """The part of Docling's `DocumentConverter` the adapter uses; a test passes a stub."""

    def convert(self, source: Path, *, raises_on_error: bool, max_file_size: int) -> _Result: ...


def missing_model_files(settings: Settings) -> list[str]:
    """Name the files of the pinned model that are not in `MODELS_PATH`; empty when the folder is complete.

    Docling does not notice an incomplete folder: it fails later, in the middle of a request, with a
    message that advises removing `artifacts_path`. A check of the whole file list at startup names the gap.
    """
    spec = MODEL_SPECS[settings.vlm_backend]
    folder = settings.models_path / spec.folder
    return [name for name in spec.files if not (folder / name).is_file()]


class DoclingParser:
    """Parses one document at a time through a Docling converter.

    The converter is built once, at startup, with the model loaded. Each call writes the bytes to a
    temporary folder under a neutral name (Docling logs the file name) and removes the folder when it
    is done, also when the conversion fails.
    """

    def __init__(
        self, converter: _Converter, *, model_id: str, max_file_size: int, work_dir: Path | None = None
    ) -> None:
        """Wire the converter; `work_dir` is where the temporary folders go (the system's by default)."""
        self._converter = converter
        self._model_id = model_id
        self._max_file_size = max_file_size
        self._work_dir = work_dir

    def parse(self, content: bytes, filename: str) -> ParseResult:
        """Convert `content`; `InvalidFile` for a document Docling cannot open, `ParseFailed` for any other failure."""
        started = time.perf_counter()
        try:
            texts = self._convert(content, filename)
        except ConversionIncomplete as exc:
            raise ParseFailed(exc.status) from exc
        except Exception as exc:  # Docling raises whatever its backends raise; the cause goes to `__cause__`
            raise ParseFailed from exc
        if texts is None:
            raise InvalidFile
        markdown, plain_text, page_count = texts
        return ParseResult(
            text=markdown,
            plain_text=plain_text,
            page_count=page_count,
            elapsed_ms=round((time.perf_counter() - started) * 1000),
            model_id=self._model_id,
        )

    def _convert(self, content: bytes, filename: str) -> tuple[str, str, int] | None:
        """Return the Markdown, the plain text and the page count; None for an input Docling marks invalid.

        A conversion that did not succeed (failure, a timeout or any partial success) raises: an
        incomplete text is never returned as if it were the document.
        """
        name = Path(filename).name or _FALLBACK_NAME
        with TemporaryDirectory(prefix="formlens-", dir=self._work_dir) as folder:
            path = Path(folder) / name
            path.write_bytes(content)
            result = self._converter.convert(path, raises_on_error=False, max_file_size=self._max_file_size)
            if not result.input.valid:
                return None
            if result.status != _SUCCESS:
                raise ConversionIncomplete(str(getattr(result.status, "value", result.status)))
            document = result.document
            return document.export_to_markdown(), document.export_to_text(), result.input.page_count


def build_docling_parser(settings: Settings) -> DoclingParser:  # pragma: no cover - loads the real model
    """Build the parser for the configured backend and load its model.

    Raises:
        ModelUnavailable: A file of the pinned model is missing from `MODELS_PATH`.
    """
    spec = MODEL_SPECS[settings.vlm_backend]
    missing = missing_model_files(settings)
    if missing:
        folder = settings.models_path / spec.folder
        msg = f"The model {spec.repo} is incomplete in {folder}: missing {', '.join(missing)}."
        raise ModelUnavailable(msg)

    # Before Docling and huggingface_hub are imported: the constant is read at import time. The
    # service makes no outbound call; a missing file is an error, never a download.
    os.environ["HF_HUB_OFFLINE"] = "1"

    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import VlmConvertOptions, VlmPipelineOptions
    from docling.datamodel.vlm_engine_options import MlxVlmEngineOptions, TransformersVlmEngineOptions
    from docling.document_converter import DocumentConverter, ImageFormatOption, PdfFormatOption
    from docling.pipeline.vlm_pipeline import VlmPipeline

    engine_options = MlxVlmEngineOptions() if settings.vlm_backend == "mlx" else TransformersVlmEngineOptions()
    pipeline_options = VlmPipelineOptions(
        vlm_options=VlmConvertOptions.from_preset("granite_docling", engine_options=engine_options),
        artifacts_path=settings.models_path,
        document_timeout=float(settings.parse_timeout_seconds),
    )
    converter = DocumentConverter(
        allowed_formats=[InputFormat.PDF, InputFormat.IMAGE],
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_cls=VlmPipeline, pipeline_options=pipeline_options),
            InputFormat.IMAGE: ImageFormatOption(pipeline_cls=VlmPipeline, pipeline_options=pipeline_options),
        },
    )
    converter.initialize_pipeline(InputFormat.PDF)
    converter.initialize_pipeline(InputFormat.IMAGE)
    log.info("model_loaded", backend=settings.vlm_backend, model=spec.repo, model_revision=spec.revision)
    return DoclingParser(converter, model_id=spec.repo, max_file_size=settings.max_upload_mb * BYTES_PER_MB)
