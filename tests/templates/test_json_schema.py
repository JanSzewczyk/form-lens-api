"""The generated JSON Schema: its shape for every type, and what a validator makes of it."""

from typing import Any

import pytest
from jsonschema import Draft202012Validator

from formlens.templates.json_schema import SCHEMA_DIALECT, build_json_schema
from formlens.templates.models import FieldType, TemplateField
from tests.templates.factories import TemplateFieldFactory

ALL_TYPES = [
    TemplateField("note", FieldType.TEXT, description="Free text", pattern="^[a-z]+$"),
    TemplateField("amount", FieldType.NUMBER, minimum=0, maximum=100.5),
    TemplateField("count", FieldType.INTEGER, minimum=1),
    TemplateField("paid", FieldType.BOOLEAN),
    TemplateField("issued", FieldType.DATE),
    TemplateField("status", FieldType.CHOICE, allowed_values=("open", "closed")),
]
VALID: dict[str, Any] = {
    "note": "abc",
    "amount": 12.5,
    "count": 3,
    "paid": True,
    "issued": "2026-02-28",
    "status": "open",
}


def validator(fields: list[TemplateField] | None = None) -> Draft202012Validator:
    return Draft202012Validator(
        build_json_schema(fields or ALL_TYPES), format_checker=Draft202012Validator.FORMAT_CHECKER
    )


def test_the_schema_is_a_valid_draft_2020_12_schema() -> None:
    schema = build_json_schema(ALL_TYPES)

    Draft202012Validator.check_schema(schema)
    assert schema["$schema"] == SCHEMA_DIALECT


def test_every_field_is_a_property_and_a_required_key_and_nothing_else_is_allowed() -> None:
    schema = build_json_schema(ALL_TYPES)

    assert list(schema["properties"]) == [item.name for item in ALL_TYPES]
    assert schema["required"] == [item.name for item in ALL_TYPES]
    assert schema["additionalProperties"] is False
    assert schema["type"] == "object"


def test_a_field_that_is_not_required_on_the_form_is_still_a_required_key_of_the_result() -> None:
    fields = [
        TemplateFieldFactory.build(name="optional", required=False),
        TemplateFieldFactory.build(name="must", required=True),
    ]

    assert build_json_schema(fields)["required"] == ["optional", "must"]


@pytest.mark.parametrize("item", ALL_TYPES, ids=[item.name for item in ALL_TYPES])
def test_null_is_allowed_for_a_field_of_every_type(item: TemplateField) -> None:
    value = build_json_schema([item])["properties"][item.name]
    nulls = [*value["type"], *value.get("enum", [])]

    assert "null" in nulls or None in nulls
    assert validator([item]).is_valid({item.name: None})


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("note", {"type": ["string", "null"], "pattern": "^[a-z]+$", "description": "Free text"}),
        ("amount", {"type": ["number", "null"], "minimum": 0, "maximum": 100.5}),
        ("count", {"type": ["integer", "null"], "minimum": 1}),
        ("paid", {"type": ["boolean", "null"]}),
        ("issued", {"type": ["string", "null"], "format": "date", "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}$"}),
        ("status", {"type": ["string", "null"], "enum": ["open", "closed", None]}),
    ],
)
def test_each_type_has_its_own_property_shape(name: str, expected: dict[str, Any]) -> None:
    assert build_json_schema(ALL_TYPES)["properties"][name] == expected


def test_a_complete_result_is_valid() -> None:
    assert validator().is_valid(VALID)


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("note", "ABC"),
        ("note", 5),
        ("amount", -0.1),
        ("amount", 100.6),
        ("amount", "12"),
        ("count", 0),
        ("count", 2.5),
        ("paid", "yes"),
        ("issued", "28.02.2026"),
        ("issued", "2026-13-45"),
        ("status", "pending"),
    ],
    ids=[
        "pattern",
        "text-as-number",
        "below-min",
        "above-max",
        "number-as-string",
        "integer-below-min",
        "integer-fraction",
        "boolean-as-text",
        "date-wrong-shape",
        "date-impossible",
        "choice-outside",
    ],
)
def test_a_value_the_field_does_not_allow_is_invalid(key: str, value: object) -> None:
    assert not validator().is_valid({**VALID, key: value})


def test_a_result_with_a_missing_or_an_extra_key_is_invalid() -> None:
    missing = {k: v for k, v in VALID.items() if k != "paid"}

    assert not validator().is_valid(missing)
    assert not validator().is_valid({**VALID, "invented": "x"})


def test_a_description_is_included_only_when_the_field_has_one() -> None:
    schema = build_json_schema(
        [TemplateFieldFactory.build(name="a", description="Label"), TemplateFieldFactory.build(name="b")]
    )

    assert schema["properties"]["a"]["description"] == "Label"
    assert "description" not in schema["properties"]["b"]


def test_the_schema_does_not_share_state_with_the_fields() -> None:
    item = TemplateField("status", FieldType.CHOICE, allowed_values=("open",))
    schema = build_json_schema([item])

    schema["properties"]["status"]["enum"].append("hacked")

    assert item.allowed_values == ("open",)
