"""The templates endpoints."""

from typing import Annotated, Final
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Response

from formlens.pagination import PageParams, get_page_params
from formlens.problems import VALIDATION_ERROR, malformed_body_response, problem_response
from formlens.templates.dependencies import get_template_service
from formlens.templates.errors import INVALID_TEMPLATE, TEMPLATE_NOT_FOUND
from formlens.templates.schemas import TemplateCreate, TemplatePage, TemplateReplace, TemplateResponse
from formlens.templates.service import TemplateService

TEMPLATES_TAG: Final = {
    "name": "templates",
    "description": "The fields a form has. An extraction reads a document against one template.",
}

router = APIRouter(prefix="/v1/templates", tags=["templates"])

_TemplateId = Annotated[UUID, Path(description="Identifier of the template.")]
_Service = Annotated[TemplateService, Depends(get_template_service)]


@router.post(
    "",
    operation_id="create_template",
    status_code=201,
    response_model=TemplateResponse,
    responses={
        400: malformed_body_response(),
        422: problem_response(
            VALIDATION_ERROR,
            INVALID_TEMPLATE,
            description=(
                "The body is not valid, for instance too many fields or a name that is too long "
                "(`validation-error`), or the template breaks a rule the schema cannot state: duplicate field "
                "names, a choice without values, a range on a non-number, a pattern that does not compile "
                "(`invalid-template`)."
            ),
        ),
    },
)
def create_template(body: TemplateCreate, service: _Service) -> TemplateResponse:
    """Create a template.

    The response carries the JSON Schema generated from the fields. Every field is a required key of the
    result that may be `null`; the schema does not depend on which fields are `required` on the form.
    """
    return TemplateResponse.from_domain(service.create(body.to_draft()))


@router.get(
    "",
    operation_id="list_templates",
    response_model=TemplatePage,
    responses={422: problem_response(VALIDATION_ERROR)},
)
def list_templates(service: _Service, page: Annotated[PageParams, Depends(get_page_params)]) -> TemplatePage:
    """List templates, oldest first, one page at a time."""
    items, total = service.page(limit=page.limit, offset=page.offset)
    return TemplatePage(
        items=[TemplateResponse.from_domain(item) for item in items],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get(
    "/{template_id}",
    operation_id="get_template",
    response_model=TemplateResponse,
    responses={404: problem_response(TEMPLATE_NOT_FOUND), 422: problem_response(VALIDATION_ERROR)},
)
def get_template(template_id: _TemplateId, service: _Service) -> TemplateResponse:
    """Return one template."""
    return TemplateResponse.from_domain(service.get(template_id))


@router.put(
    "/{template_id}",
    operation_id="replace_template",
    response_model=TemplateResponse,
    responses={
        400: malformed_body_response(),
        404: problem_response(TEMPLATE_NOT_FOUND),
        422: problem_response(
            VALIDATION_ERROR,
            INVALID_TEMPLATE,
            description=(
                "The body or the id is not valid (`validation-error`), or the template breaks a rule "
                "(`invalid-template`)."
            ),
        ),
    },
)
def replace_template(template_id: _TemplateId, body: TemplateReplace, service: _Service) -> TemplateResponse:
    """Replace a template's name, description and fields; the version goes up by one.

    The body is the whole template, not a patch.
    """
    return TemplateResponse.from_domain(service.replace(template_id, body.to_draft()))


@router.delete(
    "/{template_id}",
    operation_id="delete_template",
    status_code=204,
    response_class=Response,
    responses={404: problem_response(TEMPLATE_NOT_FOUND), 422: problem_response(VALIDATION_ERROR)},
)
def delete_template(template_id: _TemplateId, service: _Service) -> Response:
    """Delete a template."""
    service.delete(template_id)
    return Response(status_code=204)
