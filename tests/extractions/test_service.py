"""Submitting and reading an extraction, with fakes for every port."""

from datetime import timedelta
from uuid import UUID

import pytest
from structlog.testing import capture_logs

from formlens.extractions.domain.exceptions import (
    ExtractionNotFound,
    QueueFull,
    TemplateMissing,
    UploadEmpty,
    UploadTooLarge,
    UploadUnsupported,
)
from formlens.extractions.domain.model import ExtractionStatus
from formlens.extractions.service_layer.service import utc_now
from tests.extractions.factories import NOW, TEMPLATE_ID, TemplateSnapshotFactory
from tests.extractions.fakes import PDF
from tests.extractions.harness import Harness


def test_a_submitted_document_is_queued_as_pending_with_a_copy_of_the_template() -> None:
    harness = Harness()
    snapshot = TemplateSnapshotFactory.build(version=4, name="Invoice v4")
    harness.catalog.snapshots[TEMPLATE_ID] = snapshot

    extraction = harness.service.submit(PDF, TEMPLATE_ID)

    stored = harness.stored(extraction)
    assert (stored.status, stored.attempts, stored.created_at) == (ExtractionStatus.PENDING, 0, NOW)
    assert stored.template == snapshot
    assert (stored.template.version, stored.template.name) == (4, "Invoice v4")
    assert harness.repository.read_input(extraction.id) == PDF
    assert extraction.id.version == 7


def test_the_copy_does_not_change_when_the_template_does() -> None:
    harness = Harness()
    extraction = harness.service.submit(PDF, TEMPLATE_ID)

    harness.catalog.snapshots[TEMPLATE_ID] = TemplateSnapshotFactory.build(version=2, name="Edited")
    del harness.catalog.snapshots[TEMPLATE_ID]

    assert harness.stored(extraction).template.version == 1


def test_a_refused_upload_is_reported_before_the_template_is_looked_up() -> None:
    harness = Harness()

    with pytest.raises(UploadEmpty):
        harness.service.submit(b"", UUID(int=999))  # the template does not exist either
    with pytest.raises(UploadUnsupported):
        harness.service.submit(b"plain text", TEMPLATE_ID)

    assert harness.repository.count_pending() == 0


def test_an_unknown_template_is_reported_and_nothing_is_queued() -> None:
    harness = Harness()

    with pytest.raises(TemplateMissing):
        harness.service.submit(PDF, UUID(int=999))

    assert harness.repository.count_pending() == 0


def test_a_full_queue_refuses_the_submission_and_says_when_to_retry() -> None:
    harness = Harness(max_pending=2)
    harness.submit()
    harness.submit()

    with pytest.raises(QueueFull) as raised:
        harness.submit()

    assert raised.value.retry_after_seconds > 0
    assert harness.repository.count_pending() == 2


def test_submitting_logs_the_ids_and_the_size_but_not_the_document() -> None:
    harness = Harness()

    with capture_logs() as logs:
        extraction = harness.service.submit(PDF + b" SECRET-MARKER", TEMPLATE_ID)

    [line] = [entry for entry in logs if entry["event"] == "extraction_enqueued"]
    assert line["extraction_id"] == str(extraction.id)
    assert line["file_size_bytes"] == len(PDF) + len(b" SECRET-MARKER")
    assert "SECRET-MARKER" not in str(logs)


def test_a_stored_extraction_is_read_back() -> None:
    harness = Harness()
    extraction = harness.submit()

    assert harness.service.get(extraction.id) == extraction


def test_an_unknown_extraction_is_not_found() -> None:
    with pytest.raises(ExtractionNotFound):
        Harness().service.get(UUID(int=5))


def test_a_finished_extraction_is_gone_once_its_time_to_live_has_passed_even_before_the_purge() -> None:
    harness = Harness()
    extraction = harness.submit()
    assert harness.processor.run_once()
    finished_at = harness.stored(extraction).finished_at
    assert finished_at is not None

    harness.clock.now = finished_at + harness.ttl - timedelta(seconds=1)
    assert harness.service.get(extraction.id).status is ExtractionStatus.COMPLETED
    harness.clock.now = finished_at + harness.ttl

    with pytest.raises(ExtractionNotFound):
        harness.service.get(extraction.id)
    assert harness.repository.get(extraction.id) is not None  # still stored: the purge has not run


def test_the_default_clock_is_aware_utc() -> None:
    assert utc_now().utcoffset() == timedelta(0)


def test_an_upload_over_the_limit_names_the_limit() -> None:
    error = UploadTooLarge(25)

    assert (error.limit_mb, str(error)) == (25, "The file is larger than 25 MB.")
