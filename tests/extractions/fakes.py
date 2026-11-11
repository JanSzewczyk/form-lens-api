"""In-memory stand-ins for the extraction ports, and a clock a test moves by hand."""

import threading
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from formlens.extractions.domain.exceptions import (
    QueueFull,
    TemplateMissing,
    UploadEmpty,
    UploadUnsupported,
)
from formlens.extractions.domain.model import Extraction, ExtractionStatus, RecoveryCounts, TemplateSnapshot

PDF = b"%PDF-1.7 a document"
RETRY_AFTER = 30


class FakeClock:
    """A clock that only moves when a test says so."""

    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **delta: float) -> None:
        self.now += timedelta(**delta)


class FakeExtractionRepository:
    """The same rules as the SQLite repository, kept in dictionaries behind one lock."""

    def __init__(self) -> None:
        self.rows: dict[UUID, Extraction] = {}
        self.inputs: dict[UUID, bytes] = {}
        self._lock = threading.Lock()

    def add(self, extraction: Extraction, content: bytes, *, max_pending: int) -> None:
        with self._lock:
            if self._pending() >= max_pending:
                raise QueueFull(RETRY_AFTER)
            self.rows[extraction.id] = extraction
            self.inputs[extraction.id] = content

    def _pending(self) -> int:
        return sum(1 for row in self.rows.values() if row.status is ExtractionStatus.PENDING)

    def get(self, extraction_id: UUID) -> Extraction | None:
        with self._lock:
            return self.rows.get(extraction_id)

    def read_input(self, extraction_id: UUID) -> bytes | None:
        with self._lock:
            return self.inputs.get(extraction_id)

    def claim_next(self, now: datetime) -> Extraction | None:
        with self._lock:
            waiting = [row for row in self.rows.values() if row.status is ExtractionStatus.PENDING]
            if not waiting:
                return None
            oldest = min(waiting, key=lambda row: (row.created_at, row.id))
            claimed = oldest.claim(now)
            self.rows[claimed.id] = claimed
            return claimed

    def finish_if_running(self, finished: Extraction) -> bool:
        with self._lock:
            current = self.rows.get(finished.id)
            if (
                current is None
                or current.status is not ExtractionStatus.RUNNING
                or current.attempts != finished.attempts
            ):
                return False
            self.rows[finished.id] = finished
            self.inputs.pop(finished.id, None)
            return True

    def release_if_running(self, released: Extraction, *, claimed_attempts: int) -> bool:
        with self._lock:
            current = self.rows.get(released.id)
            if (
                current is None
                or current.status is not ExtractionStatus.RUNNING
                or current.attempts != claimed_attempts
            ):
                return False
            self.rows[released.id] = released
            return True

    def recover_running(self, max_attempts: int, now: datetime) -> RecoveryCounts:
        requeued = failed = 0
        with self._lock:
            for extraction_id, row in list(self.rows.items()):
                if row.status is not ExtractionStatus.RUNNING:
                    continue
                moved = row.interrupted(max_attempts, now)
                self.rows[extraction_id] = moved
                if moved.status is ExtractionStatus.PENDING:
                    requeued += 1
                else:
                    failed += 1
                    self.inputs.pop(extraction_id, None)
        return RecoveryCounts(requeued, failed)

    def purge_before(self, cutoff: datetime) -> int:
        with self._lock:
            old = [i for i, row in self.rows.items() if row.finished_at is not None and row.finished_at < cutoff]
            for extraction_id in old:
                del self.rows[extraction_id]
                self.inputs.pop(extraction_id, None)
            return len(old)

    def count_pending(self) -> int:
        with self._lock:
            return self._pending()


class FakeTextSource:
    """Returns a fixed text, raises scripted errors, or blocks until a test lets it go."""

    def __init__(
        self,
        text: str = "Invoice 42, total 10.00",
        *,
        errors: list[Exception] | None = None,
        release: threading.Event | None = None,
        max_bytes: int | None = None,
    ) -> None:
        self.text = text
        self.errors = list(errors or [])
        self.release = release
        self.max_bytes = max_bytes
        self.calls = 0
        self.started = threading.Event()

    def check(self, content: bytes) -> None:
        if not content:
            raise UploadEmpty
        if not content.startswith(b"%PDF"):
            raise UploadUnsupported

    def extract_text(self, content: bytes) -> str:
        self.calls += 1
        self.started.set()
        if self.release is not None:
            assert self.release.wait(10), "the test never released the text source"
        if self.errors:
            raise self.errors.pop(0)
        return self.text


class FakeExtractor:
    """Returns a result built from the template, raises scripted errors, or blocks until released."""

    def __init__(
        self,
        values: dict[str, Any] | None = None,
        *,
        errors: list[Exception] | None = None,
        release: threading.Event | None = None,
    ) -> None:
        self.values = values or {}
        self.errors = list(errors or [])
        self.release = release
        self.calls: list[tuple[int, UUID]] = []  # the length of the text and the template, never the text
        self.started = threading.Event()
        self.finished = threading.Event()

    def extract(self, text: str, template: TemplateSnapshot) -> dict[str, Any]:
        self.calls.append((len(text), template.template_id))
        self.started.set()
        try:
            if self.release is not None:
                assert self.release.wait(10), "the test never released the extractor"
            if self.errors:
                raise self.errors.pop(0)
            return {item.name: self.values.get(item.name) for item in template.fields}
        finally:
            self.finished.set()


class FakeTemplateCatalog:
    """Holds snapshots by id."""

    def __init__(self, *snapshots: TemplateSnapshot) -> None:
        self.snapshots = {snapshot.template_id: snapshot for snapshot in snapshots}

    def snapshot(self, template_id: UUID) -> TemplateSnapshot:
        try:
            return self.snapshots[template_id]
        except KeyError:
            raise TemplateMissing(template_id) from None
