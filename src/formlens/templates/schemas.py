"""Request and response models of the templates API."""

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from formlens.pagination import Page
from formlens.templates.json_schema import build_json_schema
from formlens.templates.models import (
    FIELD_NAME_PATTERN,
    MAX_ALLOWED_VALUE_LENGTH,
    MAX_ALLOWED_VALUES,
    MAX_DESCRIPTION_LENGTH,
    MAX_FIELD_NAME_LENGTH,
    MAX_FIELDS,
    MAX_PATTERN_LENGTH,
    MAX_TEMPLATE_NAME_LENGTH,
    FieldType,
    Template,
    TemplateDraft,
    TemplateField,
)

# The size limits are stated in the spec as well as checked by the domain, so a client can read them. The rules
# a schema cannot state (a choice needs values, a range only fits a number, names are unique, a pattern
# compiles) are answered by the domain as `invalid-template`.


class FieldSpec(BaseModel):
    """One field of a form, as a client sends it and as it is returned."""

    # The example is on the model, not on `allowed_values`, `minimum`, `maximum` and `pattern`: those only
    # fit some types, and a generator that combines per-property examples builds a text field with choices.
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [{"name": "invoice_number", "type": "text", "description": "Top right", "required": True}]
        },
    )

    name: str = Field(
        pattern=FIELD_NAME_PATTERN,
        max_length=MAX_FIELD_NAME_LENGTH,
        description="The key of the field in the extraction result: lower case letters, digits and `_`, "
        "starting with a letter. Unique within the template.",
        examples=["invoice_number"],
    )
    type: FieldType = Field(description="What the field holds.", examples=["text"])
    description: str = Field(
        default="",
        max_length=MAX_DESCRIPTION_LENGTH,
        description="How the field appears on the form (its label, where it sits). It helps the extraction.",
        examples=["Invoice number, top right"],
    )
    required: bool = Field(
        default=False,
        description="Whether a completed form must have a value. A result with a missing required field is "
        "still delivered and lists the field under `missing_required`.",
    )
    allowed_values: (
        list[Annotated[str, StringConstraints(min_length=1, max_length=MAX_ALLOWED_VALUE_LENGTH)]] | None
    ) = Field(
        default=None,
        max_length=MAX_ALLOWED_VALUES,
        description="The values a `choice` field may take; required for `choice`, refused for other types.",
    )
    minimum: float | None = Field(
        default=None,
        allow_inf_nan=False,
        description="Smallest value of a `number` or `integer` field.",
    )
    maximum: float | None = Field(
        default=None,
        allow_inf_nan=False,
        description="Largest value of a `number` or `integer` field.",
    )
    pattern: str | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_PATTERN_LENGTH,
        description="Regular expression a `text` value must match (at most 200 characters).",
    )

    def to_domain(self) -> TemplateField:
        """Build the domain field; its rules are checked there."""
        return TemplateField(
            name=self.name,
            type=self.type,
            description=self.description,
            required=self.required,
            allowed_values=tuple(self.allowed_values) if self.allowed_values is not None else None,
            minimum=self.minimum,
            maximum=self.maximum,
            pattern=self.pattern,
        )

    @classmethod
    def from_domain(cls, item: TemplateField) -> FieldSpec:
        """Describe a stored field."""
        return cls(
            name=item.name,
            type=item.type,
            description=item.description,
            required=item.required,
            allowed_values=list(item.allowed_values) if item.allowed_values is not None else None,
            minimum=item.minimum,
            maximum=item.maximum,
            pattern=item.pattern,
        )


class TemplateWrite(BaseModel):
    """The body of a create and of a replace: the whole content of a template."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(
        min_length=1,
        max_length=MAX_TEMPLATE_NAME_LENGTH,
        description="Name of the form, for people.",
        examples=["Invoice"],
    )
    description: str = Field(
        default="",
        max_length=MAX_DESCRIPTION_LENGTH,
        description="What the form is.",
        examples=["A supplier invoice with a total and a due date."],
    )
    fields: list[FieldSpec] = Field(
        min_length=1,
        max_length=MAX_FIELDS,
        description="The fields to extract, 1 to 50, with unique names.",
    )

    def to_draft(self) -> TemplateDraft:
        """Build the draft; the rules of the template are checked there (`invalid-template`)."""
        return TemplateDraft(
            name=self.name,
            description=self.description,
            fields=tuple(item.to_domain() for item in self.fields),
        )


class TemplateCreate(TemplateWrite):
    """The body of `POST /v1/templates`."""


class TemplateReplace(TemplateWrite):
    """The body of `PUT /v1/templates/{template_id}`; it replaces everything and raises the version."""


class TemplateResponse(BaseModel):
    """A stored template."""

    id: UUID = Field(description="Identifier of the template.", examples=["0192f5e0-5a3b-7c11-9d2e-3f6a1b2c4d5e"])
    name: str = Field(description="Name of the form.", examples=["Invoice"])
    description: str = Field(description="What the form is.", examples=["A supplier invoice."])
    version: int = Field(ge=1, description="Starts at 1 and grows by one with every replacement.", examples=[1])
    fields: list[FieldSpec] = Field(description="The fields to extract.")
    json_schema: dict[str, Any] = Field(
        description="The JSON Schema every extraction with this template must satisfy: one required key per "
        "field, each of which may be `null`.",
        examples=[{"type": "object", "properties": {"invoice_number": {"type": ["string", "null"]}}}],
    )
    created_at: datetime = Field(description="When the template was created (UTC).")
    updated_at: datetime = Field(description="When the template was last replaced (UTC).")

    @classmethod
    def from_domain(cls, template: Template) -> TemplateResponse:
        """Describe a stored template, with the schema generated from its fields."""
        return cls(
            id=template.id,
            name=template.name,
            description=template.description,
            version=template.version,
            fields=[FieldSpec.from_domain(item) for item in template.fields],
            json_schema=build_json_schema(template.fields),
            created_at=template.created_at,
            updated_at=template.updated_at,
        )


class TemplatePage(Page[TemplateResponse]):
    """One page of templates."""
