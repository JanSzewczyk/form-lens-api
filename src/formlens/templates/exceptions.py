"""Domain errors of the templates; they know nothing of HTTP."""

from uuid import UUID


class TemplateNotFound(Exception):
    """No template has this id."""

    def __init__(self, template_id: UUID) -> None:
        """Name the id that was asked for."""
        super().__init__(f"Template {template_id} does not exist.")
        self.template_id = template_id


class InvalidTemplate(Exception):
    """A template breaks one of its own rules.

    The message names the field and the rule. It never holds a value the client sent: a pattern or a
    choice can be a personal identifier.
    """

    def __init__(self, rule: str, *, field: str | None = None) -> None:
        """Name the broken rule and, when the rule is about one field, which position or name it has."""
        where = f"Field {field}: " if field is not None else ""
        super().__init__(f"{where}{rule}")
        self.rule = rule
        self.field = field
