"""Test data for the extractions."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from factory.base import Factory
from factory.declarations import LazyFunction, Sequence

from formlens.extractions.domain.model import Extraction, ExtractionStatus, SnapshotField, TemplateSnapshot

NOW = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
TEMPLATE_ID = UUID(int=0xABC)


class SnapshotFieldFactory(Factory[SnapshotField]):
    """A required text field."""

    class Meta:
        model = SnapshotField

    name = Sequence(lambda n: f"field_{n}")  # type: ignore[no-untyped-call]  # factory_boy declarations are untyped
    type = "text"
    description = ""
    required = False


def _schema(names: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {name: {"type": ["string", "null"]} for name in names},
        "required": names,
        "additionalProperties": False,
    }


class TemplateSnapshotFactory(Factory[TemplateSnapshot]):
    """A snapshot of a template with two fields, `number` (required) and `buyer`."""

    class Meta:
        model = TemplateSnapshot

    template_id = TEMPLATE_ID
    version = 1
    name = "Invoice"
    fields = LazyFunction(  # type: ignore[no-untyped-call]  # factory_boy declarations are untyped
        lambda: (SnapshotFieldFactory.build(name="number", required=True), SnapshotFieldFactory.build(name="buyer"))
    )
    json_schema = LazyFunction(lambda: _schema(["number", "buyer"]))  # type: ignore[no-untyped-call]  # factory_boy declarations are untyped


class ExtractionFactory(Factory[Extraction]):
    """A pending extraction created at `NOW`; pass `id` and `created_at` when a test depends on them."""

    class Meta:
        model = Extraction

    id = Sequence(lambda n: UUID(int=n + 1))  # type: ignore[no-untyped-call]  # factory_boy declarations are untyped
    template = LazyFunction(TemplateSnapshotFactory.build)  # type: ignore[no-untyped-call]  # factory_boy declarations are untyped
    status = ExtractionStatus.PENDING
    attempts = 0
    created_at = NOW
