"""The template and its rules: plain data, standard library only.

A template is the list of fields a form has. The rules of a field (a choice has values, a range needs a
number) and of the whole list (no duplicate names, a bounded size) are checked when the object is built, so
a `Template` that exists is valid. Every message names a field and a rule, never a value.
"""

import math
import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final, NoReturn
from uuid import UUID

from formlens.templates.exceptions import InvalidTemplate

MAX_FIELDS: Final = 50
MAX_TEMPLATE_NAME_LENGTH: Final = 100
MAX_DESCRIPTION_LENGTH: Final = 300
MAX_FIELD_NAME_LENGTH: Final = 64
MAX_ALLOWED_VALUES: Final = 50
MAX_ALLOWED_VALUE_LENGTH: Final = 100
# A pattern comes from a client and runs on every document, so its size is bounded.
MAX_PATTERN_LENGTH: Final = 200

# A field name is a JSON key of the result: lower case, no leading underscore or digit, so it can never be
# `__proto__`, `constructor` or a key a client library treats specially.
_FIELD_NAME: Final = re.compile(r"[a-z][a-z0-9_]*")


class FieldType(StrEnum):
    """What a field holds."""

    TEXT = "text"
    NUMBER = "number"
    INTEGER = "integer"
    BOOLEAN = "boolean"
    DATE = "date"
    CHOICE = "choice"


_NUMERIC: Final = frozenset({FieldType.NUMBER, FieldType.INTEGER})


@dataclass(frozen=True, slots=True)
class TemplateField:
    """One field of a form: a JSON key, a type and the limits the type allows."""

    name: str
    type: FieldType
    description: str = ""
    required: bool = False
    allowed_values: tuple[str, ...] | None = None
    minimum: float | None = None
    maximum: float | None = None
    pattern: str | None = None

    def __post_init__(self) -> None:
        """Refuse a field that breaks a rule of its type."""
        self._check_name()
        self._check_text()
        if len(self.description) > MAX_DESCRIPTION_LENGTH:
            self._refuse(f"description is longer than {MAX_DESCRIPTION_LENGTH} characters")
        self._check_choice()
        self._check_range()
        self._check_pattern()

    def _refuse(self, rule: str) -> NoReturn:
        """Fail with the name of this field; the name passed `_check_name`, so it is safe to quote."""
        raise InvalidTemplate(rule, field=self.name)

    def _check_name(self) -> None:
        if len(self.name) > MAX_FIELD_NAME_LENGTH or not _FIELD_NAME.fullmatch(self.name):
            # Not quoted: a name that fails is not known to be safe.
            msg = (
                f"a field name must be 1 to {MAX_FIELD_NAME_LENGTH} characters of a-z, 0-9 and _, "
                "starting with a letter"
            )
            raise InvalidTemplate(msg)

    def _check_text(self) -> None:
        texts = (self.description, self.pattern or "", *(self.allowed_values or ()))
        if not all(_is_storable(text) for text in texts):
            self._refuse("text must be valid Unicode (a lone surrogate cannot be stored)")

    def _check_choice(self) -> None:
        if self.type is not FieldType.CHOICE:
            if self.allowed_values is not None:
                self._refuse("allowed_values is only for the type choice")
            return
        if not self.allowed_values:
            self._refuse("the type choice needs allowed_values")
        if len(self.allowed_values) > MAX_ALLOWED_VALUES:
            self._refuse(f"allowed_values has more than {MAX_ALLOWED_VALUES} values")
        if len(set(self.allowed_values)) != len(self.allowed_values):
            self._refuse("allowed_values repeats a value")
        if any(not value or len(value) > MAX_ALLOWED_VALUE_LENGTH for value in self.allowed_values):
            self._refuse(f"each allowed value must be 1 to {MAX_ALLOWED_VALUE_LENGTH} characters")

    def _check_range(self) -> None:
        if self.minimum is None and self.maximum is None:
            return
        if self.type not in _NUMERIC:
            self._refuse("minimum and maximum are only for the types number and integer")
        if not all(math.isfinite(limit) for limit in (self.minimum, self.maximum) if limit is not None):
            self._refuse("minimum and maximum must be finite numbers")
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            self._refuse("minimum is greater than maximum")

    def _check_pattern(self) -> None:
        if self.pattern is None:
            return
        if self.type is not FieldType.TEXT:
            self._refuse("pattern is only for the type text")
        if not self.pattern or len(self.pattern) > MAX_PATTERN_LENGTH:
            self._refuse(f"pattern must be 1 to {MAX_PATTERN_LENGTH} characters")
        try:
            re.compile(self.pattern)
        except re.error, OverflowError, RecursionError:
            # `a{4294967295}` raises OverflowError and a deeply nested group RecursionError, not re.error.
            self._refuse("pattern is not a valid regular expression")


def _is_storable(text: str) -> bool:
    """Tell whether `text` can be written as UTF-8; a lone surrogate such as U+D800 cannot."""
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def _check_definition(name: str, description: str, fields: tuple[TemplateField, ...]) -> None:
    """The rules of the template as a whole."""
    if not _is_storable(name) or not _is_storable(description):
        raise InvalidTemplate("text must be valid Unicode (a lone surrogate cannot be stored)")
    if not name.strip() or len(name) > MAX_TEMPLATE_NAME_LENGTH:
        raise InvalidTemplate(f"name must be 1 to {MAX_TEMPLATE_NAME_LENGTH} characters")
    if len(description) > MAX_DESCRIPTION_LENGTH:
        raise InvalidTemplate(f"description is longer than {MAX_DESCRIPTION_LENGTH} characters")
    if not fields:
        raise InvalidTemplate("a template needs at least one field")
    if len(fields) > MAX_FIELDS:
        raise InvalidTemplate(f"a template has at most {MAX_FIELDS} fields")
    seen: set[str] = set()
    for item in fields:
        if item.name in seen:
            raise InvalidTemplate("field names must be unique", field=item.name)
        seen.add(item.name)


@dataclass(frozen=True, slots=True)
class TemplateDraft:
    """What a client sends to create or replace a template; valid as soon as it exists."""

    name: str
    fields: tuple[TemplateField, ...]
    description: str = ""

    def __post_init__(self) -> None:
        """Refuse a draft that breaks a rule of the template."""
        _check_definition(self.name, self.description, self.fields)


@dataclass(frozen=True, slots=True)
class Template:
    """A stored template. `version` starts at 1 and grows by one with every replacement."""

    id: UUID
    name: str
    fields: tuple[TemplateField, ...]
    version: int
    created_at: datetime
    updated_at: datetime
    description: str = ""

    def __post_init__(self) -> None:
        """Refuse a template that breaks a rule."""
        _check_definition(self.name, self.description, self.fields)
        if self.version < 1:
            msg = "version starts at 1"
            raise ValueError(msg)

    @classmethod
    def create(cls, template_id: UUID, draft: TemplateDraft, now: datetime) -> Template:
        """Return the first version of a template."""
        return cls(
            id=template_id,
            name=draft.name,
            description=draft.description,
            fields=draft.fields,
            version=1,
            created_at=now,
            updated_at=now,
        )
