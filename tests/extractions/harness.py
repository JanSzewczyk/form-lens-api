"""One processor, one service and their fakes wired together, for the lifecycle tests."""

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta
from uuid import UUID

from formlens.extractions.adapters.deadline import ThreadDeadline
from formlens.extractions.domain.model import Extraction
from formlens.extractions.domain.ports import ExtractionRepository
from formlens.extractions.service_layer.processor import ExtractionProcessor, ProcessorConfig
from formlens.extractions.service_layer.service import ExtractionService
from tests.extractions.factories import NOW, TEMPLATE_ID, TemplateSnapshotFactory
from tests.extractions.fakes import (
    PDF,
    FakeClock,
    FakeExtractionRepository,
    FakeExtractor,
    FakeTemplateCatalog,
    FakeTextSource,
)


def wait_until(condition: Callable[[], bool], *, timeout: float = 5.0) -> bool:
    """Poll until `condition` holds; False when it never did within `timeout`."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.005)
    return condition()


@dataclass
class Harness:
    """The pieces of the extraction stack, built from fakes."""

    repository: ExtractionRepository = field(default_factory=FakeExtractionRepository)
    text_source: FakeTextSource = field(default_factory=FakeTextSource)
    extractor: FakeExtractor = field(default_factory=FakeExtractor)
    clock: FakeClock = field(default_factory=lambda: FakeClock(NOW))
    deadline: ThreadDeadline = field(default_factory=ThreadDeadline)
    max_attempts: int = 2
    job_timeout_seconds: float = 5.0
    ttl: timedelta = timedelta(hours=24)
    max_input_chars: int = 1000
    max_pending: int = 100

    def __post_init__(self) -> None:
        self.catalog = FakeTemplateCatalog(TemplateSnapshotFactory.build())

    @property
    def processor(self) -> ExtractionProcessor:
        config = ProcessorConfig(self.max_attempts, self.job_timeout_seconds, self.ttl, self.max_input_chars)
        return ExtractionProcessor(
            self.repository, self.text_source, self.extractor, self.deadline, config, clock=self.clock
        )

    @property
    def service(self) -> ExtractionService:
        return ExtractionService(
            self.repository,
            self.text_source,
            self.catalog,
            max_pending=self.max_pending,
            result_ttl=self.ttl,
            clock=self.clock,
        )

    def submit(self, content: bytes = PDF, template_id: UUID = TEMPLATE_ID) -> Extraction:
        """Queue a document; later submissions are one second newer, so the order is the order of the calls."""
        extraction = self.service.submit(content, template_id)
        self.clock.advance(seconds=1)
        return extraction

    def stored(self, extraction: Extraction) -> Extraction:
        row = self.repository.get(extraction.id)
        assert row is not None
        return row
