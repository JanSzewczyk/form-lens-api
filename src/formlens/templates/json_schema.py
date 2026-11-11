"""The JSON Schema a template stands for: what an extraction result must look like.

Pure: fields in, a dictionary out. Every field is a required key whose value may be `null` (the model is told
to return `null` for what the form does not show, never to guess), so the schema works for the
structured-output mode of the model and as the contract the result is validated against. Whether a field is
`required` on the form is not part of this schema; the extraction reports that separately.
"""

from collections.abc import Iterable
from typing import Any, Final

from formlens.templates.models import FieldType, TemplateField

SCHEMA_DIALECT: Final = "https://json-schema.org/draft/2020-12/schema"
# `format: date` is an annotation unless a validator turns it on, so the pattern states the shape too.
_ISO_DATE_PATTERN: Final = r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$"


def _property(item: TemplateField) -> dict[str, Any]:
    """Describe one field; `null` is always allowed."""
    prop: dict[str, Any]
    match item.type:
        case FieldType.TEXT:
            prop = {"type": ["string", "null"]}
            if item.pattern is not None:
                prop["pattern"] = item.pattern
        case FieldType.NUMBER | FieldType.INTEGER:
            prop = {"type": [item.type.value, "null"]}
            if item.minimum is not None:
                prop["minimum"] = item.minimum
            if item.maximum is not None:
                prop["maximum"] = item.maximum
        case FieldType.BOOLEAN:
            prop = {"type": ["boolean", "null"]}
        case FieldType.DATE:
            prop = {"type": ["string", "null"], "format": "date", "pattern": _ISO_DATE_PATTERN}
        case FieldType.CHOICE:
            prop = {"type": ["string", "null"], "enum": [*(item.allowed_values or ()), None]}
    if item.description:
        prop["description"] = item.description
    return prop


def build_json_schema(fields: Iterable[TemplateField]) -> dict[str, Any]:
    """Return the schema of an object with one required, nullable key per field and no other key."""
    items = list(fields)
    return {
        "$schema": SCHEMA_DIALECT,
        "type": "object",
        "properties": {item.name: _property(item) for item in items},
        "required": [item.name for item in items],
        "additionalProperties": False,
    }
