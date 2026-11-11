"""One problem type per template error, and the mapping the app registers."""

from typing import Final

from formlens.problems import ProblemType
from formlens.templates.exceptions import InvalidTemplate, TemplateNotFound

TEMPLATE_NOT_FOUND: Final = ProblemType("template-not-found", "Template not found", 404)
INVALID_TEMPLATE: Final = ProblemType("invalid-template", "Invalid template", 422)

ERRORS: Final[dict[type[Exception], ProblemType]] = {
    TemplateNotFound: TEMPLATE_NOT_FOUND,
    InvalidTemplate: INVALID_TEMPLATE,
}
