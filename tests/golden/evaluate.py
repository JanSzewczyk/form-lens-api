"""`make evaluate`: read the golden set with the real parser and the local model, and score the answers.

    uv run python -m tests.golden.evaluate [--limit N] [--refresh-text] [--output PATH]

It needs what the service needs: the downloaded document model (`make download-models`) and a running Ollama with
the model of `LLM_MODEL` pulled (see docs/how-to/run-the-llm.md). It stops with a clear message, and a non-zero
exit status, when either is missing; it never prints numbers from a run that did not happen.

The parsed text of each document is cached under `.golden/text/` (the key holds a hash of the file), so a change
of prompt or model is measured without running the document model again. `--refresh-text` parses again.
"""

import argparse
import hashlib
import sys
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final
from uuid import UUID

import httpx2

from formlens.config import Settings
from formlens.extractions.adapters.ollama_extractor import PROMPT_VERSION, OllamaFieldExtractor
from formlens.extractions.adapters.parsing_text_source import ParsingTextSource
from formlens.extractions.domain.exceptions import JobError
from formlens.extractions.domain.model import SnapshotField, TemplateSnapshot
from formlens.extractions.domain.ports import FieldExtractor, TextSource
from formlens.parsing.exceptions import ModelUnavailable
from formlens.parsing.service import DocumentService
from formlens.parsing.slots import ParseSlots
from formlens.templates.json_schema import build_json_schema
from formlens.templates.models import TemplateField
from tests.golden.generator import GoldenDocument, generate
from tests.golden.scoring import Report, render_markdown, render_table, score_document
from tests.golden.templates import TEMPLATES

CACHE_DIR: Final = Path(".golden") / "text"
DEFAULT_OUTPUT: Final = Path(".golden") / "report.md"
EXIT_NOT_READY: Final = 2


class NotReadyError(Exception):
    """Something the run needs is missing; the message says what to do."""


def snapshot(key: str, fields: Sequence[TemplateField]) -> TemplateSnapshot:
    """Return the template as the extraction sees it: plain fields and the generated schema."""
    return TemplateSnapshot(
        template_id=_uuid_of(key),
        version=1,
        name=key,
        fields=tuple(SnapshotField(f.name, f.type.value, f.description, f.required) for f in fields),
        json_schema=build_json_schema(fields),
    )


def _uuid_of(key: str) -> Any:

    return UUID(bytes=hashlib.sha256(key.encode()).digest()[:16])


def cached_text(source: TextSource, directory: Path, *, refresh: bool) -> Callable[[GoldenDocument], str]:
    """Return a function that reads a document's text, from `directory` when it was read before."""

    def read(document: GoldenDocument) -> str:
        digest = hashlib.sha256(document.content).hexdigest()[:16]
        path = directory / f"{document.id}-{digest}.txt"
        if path.exists() and not refresh:
            return path.read_text(encoding="utf-8")
        text = source.extract_text(document.content)
        directory.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return text

    return read


def evaluate(
    documents: Sequence[GoldenDocument], text_of: Callable[[GoldenDocument], str], extractor: FieldExtractor
) -> Report:
    """Run every document through the extractor and score the answers."""
    report = Report()
    for document in documents:
        fields = TEMPLATES[document.template]
        types = {f.name: f.type.value for f in fields}
        try:
            actual: dict[str, Any] | None = extractor.extract(text_of(document), snapshot(document.template, fields))
        except JobError:
            actual = None  # the failure is counted; its message is never shown
        report.add(score_document(document.id, document.expected, actual, types), failed=actual is None)
    return report


def check_ollama(base_url: str, model: str) -> None:
    """Raise `NotReadyError` unless Ollama answers at `base_url` and lists `model`."""
    try:
        with httpx2.Client(timeout=5.0, trust_env=False) as client:
            response = client.get(f"{base_url.rstrip('/')}/models")
    except httpx2.HTTPError:
        msg = (
            f"Ollama does not answer at {base_url}. Start it (`ollama serve`) and pull the model "
            f"(`ollama pull {model}`); see docs/how-to/run-the-llm.md."
        )
        raise NotReadyError(msg) from None
    try:
        names = {item["id"] for item in response.json()["data"]}
    except ValueError, KeyError, TypeError:
        return  # an answer that does not list models: the first extraction will say what is wrong
    if model not in names:
        msg = (
            f"Ollama is running but `{model}` is not pulled. Run `ollama pull {model}`; see docs/how-to/run-the-llm.md."
        )
        raise NotReadyError(msg)


def docling_text_source(settings: Settings) -> TextSource:
    """Load the real document model, or raise `NotReadyError` with what to do."""
    from formlens.parsing.docling_parser import build_docling_parser  # heavy: only when used

    try:
        parser = build_docling_parser(settings)
    except ModelUnavailable:
        msg = "The document model is not downloaded. Run `make download-models`, then `make evaluate` again."
        raise NotReadyError(msg) from None
    service = DocumentService(parser, ParseSlots(1), max_upload_mb=settings.max_upload_mb)
    return ParsingTextSource(service, max_upload_mb=settings.max_upload_mb)


def main(
    argv: Sequence[str] | None = None,
    *,
    settings: Settings | None = None,
    text_source: TextSource | None = None,
    extractor: FieldExtractor | None = None,
    cache_dir: Path = CACHE_DIR,
) -> int:
    """Run the evaluation; return the exit status (0 done, 2 something is missing)."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--limit", type=int, default=None, help="only the first N documents")
    parser.add_argument("--refresh-text", action="store_true", help="parse again instead of reading the cache")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="where to write the Markdown section")
    args = parser.parse_args(argv)
    settings = settings or Settings()
    documents = generate()[: args.limit]
    owned: OllamaFieldExtractor | None = None
    try:
        if extractor is None:
            check_ollama(settings.llm_base_url, settings.llm_model)
            owned = extractor = OllamaFieldExtractor(
                base_url=settings.llm_base_url, model=settings.llm_model, timeout_seconds=settings.llm_timeout_seconds
            )
        text_of = _text_reader(documents, text_source, settings, cache_dir, refresh=args.refresh_text)
        report = evaluate(documents, text_of, extractor)
    except NotReadyError as error:
        sys.stderr.write(f"evaluate: {error}\n")
        return EXIT_NOT_READY
    finally:
        if owned is not None:
            owned.close()
    print(render_table(report))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        render_markdown(
            report, model=settings.llm_model, prompt_version=PROMPT_VERSION, date=datetime.now(UTC).date().isoformat()
        ),
        encoding="utf-8",
    )
    print(f"\nMarkdown section written to {args.output}")
    return 0


def _text_reader(
    documents: Sequence[GoldenDocument],
    source: TextSource | None,
    settings: Settings,
    cache_dir: Path,
    *,
    refresh: bool,
) -> Callable[[GoldenDocument], str]:
    """Return the text reader; the document model is loaded only if some text is not cached yet."""
    if source is not None:
        return cached_text(source, cache_dir, refresh=refresh)
    if not refresh and all(_is_cached(document, cache_dir) for document in documents):
        return cached_text(_NoSource(), cache_dir, refresh=False)
    return cached_text(docling_text_source(settings), cache_dir, refresh=refresh)


def _is_cached(document: GoldenDocument, cache_dir: Path) -> bool:
    digest = hashlib.sha256(document.content).hexdigest()[:16]
    return (cache_dir / f"{document.id}-{digest}.txt").exists()


class _NoSource:
    """Stands in for the document model when every text is cached; asked for text, it says that is a bug."""

    def check(self, content: bytes) -> None:  # pragma: no cover - never called
        raise AssertionError

    def extract_text(self, content: bytes) -> str:  # pragma: no cover - never called
        raise AssertionError


if __name__ == "__main__":
    raise SystemExit(main())
