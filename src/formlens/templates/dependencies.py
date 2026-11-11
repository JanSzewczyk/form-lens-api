"""Builds what a request needs from the objects the app owns."""

from typing import Annotated, cast

from fastapi import Depends, Request

from formlens.templates.repository import TemplateRepository
from formlens.templates.service import TemplateService


def get_template_repository(request: Request) -> TemplateRepository:
    """Return the repository the app was built with."""
    return cast("TemplateRepository", request.app.state.template_repository)


def get_template_service(
    repository: Annotated[TemplateRepository, Depends(get_template_repository)],
) -> TemplateService:
    """Build the service for one request."""
    return TemplateService(repository)
