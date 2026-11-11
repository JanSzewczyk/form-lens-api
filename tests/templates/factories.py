"""Test data for the templates: domain objects and request bodies. Set every value a test asserts on."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from factory.base import Factory
from factory.declarations import LazyFunction, Sequence, Trait

from formlens.templates.models import FieldType, Template, TemplateDraft, TemplateField

NOW = datetime(2026, 1, 15, 9, 30, tzinfo=UTC)


class TemplateFieldFactory(Factory[TemplateField]):
    """A text field; the traits make the other types with what each one needs."""

    class Meta:
        model = TemplateField

    name = Sequence(lambda n: f"field_{n}")  # type: ignore[no-untyped-call]  # factory_boy declarations are untyped
    type = FieldType.TEXT
    description = ""
    required = False

    class Params:
        number = Trait(type=FieldType.NUMBER)  # type: ignore[no-untyped-call]  # factory_boy declarations are untyped
        integer = Trait(type=FieldType.INTEGER)  # type: ignore[no-untyped-call]  # factory_boy declarations are untyped
        boolean = Trait(type=FieldType.BOOLEAN)  # type: ignore[no-untyped-call]  # factory_boy declarations are untyped
        date = Trait(type=FieldType.DATE)  # type: ignore[no-untyped-call]  # factory_boy declarations are untyped
        choice = Trait(  # type: ignore[no-untyped-call]  # factory_boy declarations are untyped
            type=FieldType.CHOICE, allowed_values=("open", "closed")
        )


class TemplateDraftFactory(Factory[TemplateDraft]):
    """A draft with two text fields."""

    class Meta:
        model = TemplateDraft

    name = Sequence(lambda n: f"Form {n}")  # type: ignore[no-untyped-call]  # factory_boy declarations are untyped
    description = ""
    fields = LazyFunction(lambda: (TemplateFieldFactory.build(), TemplateFieldFactory.build()))  # type: ignore[no-untyped-call]  # factory_boy declarations are untyped


class TemplateFactory(Factory[Template]):
    """A stored template at version 1."""

    class Meta:
        model = Template

    id = LazyFunction(lambda: UUID(int=1))  # type: ignore[no-untyped-call]  # factory_boy declarations are untyped
    name = Sequence(lambda n: f"Form {n}")  # type: ignore[no-untyped-call]  # factory_boy declarations are untyped
    description = ""
    version = 1
    created_at = NOW
    updated_at = NOW
    fields = LazyFunction(lambda: (TemplateFieldFactory.build(),))  # type: ignore[no-untyped-call]  # factory_boy declarations are untyped


def field_body(**overrides: Any) -> dict[str, Any]:
    """A request body for one field: a text field named `customer`."""
    return {"name": "customer", "type": "text", **overrides}


def template_body(**overrides: Any) -> dict[str, Any]:
    """A request body for a template with one text field named `customer`."""
    return {"name": "Order form", "fields": [field_body()], **overrides}
