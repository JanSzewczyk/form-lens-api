"""The rules of a template, checked on the domain objects with no database and no HTTP."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest

from formlens.templates.exceptions import InvalidTemplate
from formlens.templates.models import (
    MAX_ALLOWED_VALUES,
    MAX_FIELDS,
    MAX_PATTERN_LENGTH,
    FieldType,
    Template,
    TemplateDraft,
    TemplateField,
)
from tests.templates.factories import NOW, TemplateDraftFactory, TemplateFactory, TemplateFieldFactory


def test_a_field_of_every_type_is_valid_with_what_its_type_allows() -> None:
    fields = [
        TemplateField("a", FieldType.TEXT, pattern="^[A-Z]+$"),
        TemplateField("b", FieldType.NUMBER, minimum=0.5, maximum=9.5),
        TemplateField("c", FieldType.INTEGER, minimum=1, maximum=1),
        TemplateField("d", FieldType.BOOLEAN),
        TemplateField("e", FieldType.DATE),
        TemplateField("f", FieldType.CHOICE, allowed_values=("x", "y")),
    ]

    assert [item.type for item in fields] == list(FieldType)


@pytest.mark.parametrize(
    ("kwargs", "rule"),
    [
        pytest.param(
            {"type": FieldType.TEXT, "allowed_values": ("a",)}, "allowed_values is only for", id="values-on-text"
        ),
        pytest.param({"type": FieldType.CHOICE}, "needs allowed_values", id="choice-without-values"),
        pytest.param({"type": FieldType.CHOICE, "allowed_values": ()}, "needs allowed_values", id="choice-empty"),
        pytest.param({"type": FieldType.CHOICE, "allowed_values": ("a", "a")}, "repeats a value", id="choice-repeats"),
        pytest.param(
            {"type": FieldType.CHOICE, "allowed_values": ("a", "")}, "each allowed value", id="choice-blank-value"
        ),
        pytest.param(
            {"type": FieldType.CHOICE, "allowed_values": tuple(str(i) for i in range(MAX_ALLOWED_VALUES + 1))},
            "more than",
            id="choice-too-many",
        ),
        pytest.param({"type": FieldType.TEXT, "minimum": 1}, "only for the types number", id="range-on-text"),
        pytest.param({"type": FieldType.DATE, "maximum": 1}, "only for the types number", id="range-on-date"),
        pytest.param({"type": FieldType.NUMBER, "minimum": 5, "maximum": 4}, "greater than maximum", id="min-over-max"),
        pytest.param({"type": FieldType.NUMBER, "minimum": float("nan")}, "finite", id="min-nan"),
        pytest.param({"type": FieldType.INTEGER, "maximum": float("inf")}, "finite", id="max-infinite"),
        pytest.param({"type": FieldType.NUMBER, "pattern": "^1$"}, "pattern is only for", id="pattern-on-number"),
        pytest.param({"type": FieldType.TEXT, "pattern": ""}, "pattern must be 1 to", id="pattern-empty"),
        pytest.param(
            {"type": FieldType.TEXT, "pattern": "a" * (MAX_PATTERN_LENGTH + 1)},
            "pattern must be 1 to",
            id="pattern-long",
        ),
        pytest.param({"type": FieldType.TEXT, "pattern": "(unclosed"}, "not a valid regular", id="pattern-invalid"),
        pytest.param(
            {"type": FieldType.TEXT, "pattern": "a{4294967295}"}, "not a valid regular", id="pattern-repeat-overflow"
        ),
        pytest.param({"type": FieldType.TEXT, "description": "\ud800"}, "valid Unicode", id="description-surrogate"),
        pytest.param({"type": FieldType.TEXT, "pattern": "\ud800"}, "valid Unicode", id="pattern-surrogate"),
        pytest.param(
            {"type": FieldType.CHOICE, "allowed_values": ("a", "\ud800")}, "valid Unicode", id="value-surrogate"
        ),
        pytest.param(
            {"type": FieldType.TEXT, "description": "d" * 301}, "description is longer", id="description-long"
        ),
    ],
)
def test_a_field_that_breaks_a_rule_of_its_type_is_refused_and_named(kwargs: dict[str, Any], rule: str) -> None:
    with pytest.raises(InvalidTemplate, match=rule) as raised:
        TemplateFieldFactory.build(name="amount", **kwargs)

    assert raised.value.field == "amount"
    assert str(raised.value).startswith("Field amount: ")


@pytest.mark.parametrize(
    "name",
    ["", "Amount", "1st", "_hidden", "__proto__", "has space", "dash-ed", "a" * 65, "zażółć", "a\n"],
    ids=[
        "empty",
        "capital",
        "digit-first",
        "underscore-first",
        "proto",
        "space",
        "dash",
        "too-long",
        "non-ascii",
        "newline",
    ],
)
def test_an_unsafe_field_name_is_refused_without_quoting_it(name: str) -> None:
    with pytest.raises(InvalidTemplate, match="a field name must be") as raised:
        TemplateFieldFactory.build(name=name)

    assert raised.value.field is None
    assert name == "" or name not in str(raised.value)


def test_a_rule_message_never_holds_the_values_the_client_sent() -> None:
    secret = "SECRET-123-ZZ"  # a marker, not a credential
    with pytest.raises(InvalidTemplate) as raised:
        TemplateFieldFactory.build(name="id_number", type=FieldType.NUMBER, pattern=secret, allowed_values=(secret,))

    assert secret not in str(raised.value)


def test_a_draft_needs_between_one_and_the_maximum_number_of_fields() -> None:
    with pytest.raises(InvalidTemplate, match="at least one field"):
        TemplateDraftFactory.build(fields=())
    with pytest.raises(InvalidTemplate, match=f"at most {MAX_FIELDS} fields"):
        TemplateDraftFactory.build(fields=tuple(TemplateFieldFactory.build_batch(MAX_FIELDS + 1)))

    assert (
        len(TemplateDraftFactory.build(fields=tuple(TemplateFieldFactory.build_batch(MAX_FIELDS))).fields) == MAX_FIELDS
    )


def test_two_fields_with_the_same_name_are_refused_and_the_name_is_given() -> None:
    fields = (TemplateFieldFactory.build(name="total"), TemplateFieldFactory.build(name="total", number=True))

    with pytest.raises(InvalidTemplate, match="field names must be unique") as raised:
        TemplateDraftFactory.build(fields=fields)

    assert raised.value.field == "total"


def test_a_template_name_or_description_with_a_lone_surrogate_is_refused() -> None:
    with pytest.raises(InvalidTemplate, match="valid Unicode"):
        TemplateDraftFactory.build(name="\ud800")
    with pytest.raises(InvalidTemplate, match="valid Unicode"):
        TemplateDraftFactory.build(description="\ud800")


@pytest.mark.parametrize("name", ["", "   ", "n" * 101], ids=["empty", "blank", "long"])
def test_a_template_name_must_have_text_and_stay_short(name: str) -> None:
    with pytest.raises(InvalidTemplate, match="name must be 1 to 100"):
        TemplateDraftFactory.build(name=name)


def test_a_template_description_is_bounded() -> None:
    with pytest.raises(InvalidTemplate, match="description is longer"):
        TemplateDraftFactory.build(description="d" * 301)


def test_a_stored_template_obeys_the_same_rules_as_a_draft() -> None:
    with pytest.raises(InvalidTemplate, match="at least one field"):
        TemplateFactory.build(fields=())


def test_the_first_version_of_a_template_is_one_and_both_times_are_the_creation_time() -> None:
    draft = TemplateDraftFactory.build(name="Invoice", description="Supplier invoice")
    template_id = UUID(int=7)

    template = Template.create(template_id, draft, NOW)

    assert (template.id, template.version, template.created_at, template.updated_at) == (template_id, 1, NOW, NOW)
    assert (template.name, template.description, template.fields) == ("Invoice", "Supplier invoice", draft.fields)


def test_a_version_below_one_is_a_programming_error() -> None:
    with pytest.raises(ValueError, match="version starts at 1"):
        TemplateFactory.build(version=0, created_at=datetime(2026, 1, 1, tzinfo=UTC))


def test_a_draft_is_immutable() -> None:
    draft = TemplateDraft(name="Invoice", fields=(TemplateFieldFactory.build(),))

    with pytest.raises(AttributeError):
        draft.name = "Other"  # type: ignore[misc]  # frozen on purpose
