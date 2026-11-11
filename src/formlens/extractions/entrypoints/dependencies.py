"""Builds what a request needs from the objects the app owns."""

from datetime import timedelta
from typing import Annotated, cast

from fastapi import Depends, FastAPI, Request

from formlens.config import Settings, get_settings
from formlens.extractions.adapters.parsing_text_source import ParsingTextSource
from formlens.extractions.adapters.template_catalog import TemplateServiceCatalog
from formlens.extractions.domain.ports import ExtractionRepository
from formlens.extractions.service_layer.service import ExtractionService
from formlens.parsing.dependencies import get_slots
from formlens.parsing.exceptions import ModelUnavailable
from formlens.parsing.ports import DocumentParser, ParseResult
from formlens.parsing.service import DocumentService
from formlens.parsing.slots import ParseSlots
from formlens.templates.dependencies import get_template_service
from formlens.templates.service import TemplateService


def get_extraction_repository(request: Request) -> ExtractionRepository:
    """Return the repository the app was built with."""
    return cast("ExtractionRepository", request.app.state.extraction_repository)


class _AppParser:
    """The parser the app has loaded, looked up at the moment it is used.

    A request only needs it for the upload checks, which never call it, so a request must not fail because the
    model is not loaded yet (reading an extraction never needs a model).
    """

    def __init__(self, app: FastAPI) -> None:
        self._app = app

    def parse(self, content: bytes, filename: str) -> ParseResult:
        parser = cast("DocumentParser | None", self._app.state.parser)
        if parser is None:
            raise ModelUnavailable
        return parser.parse(content, filename)


def get_extraction_service(
    request: Request,
    repository: Annotated[ExtractionRepository, Depends(get_extraction_repository)],
    slots: Annotated[ParseSlots, Depends(get_slots)],
    templates: Annotated[TemplateService, Depends(get_template_service)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> ExtractionService:
    """Build the service for one request.

    The text source goes through the same `DocumentService`, and so the same parser slots, as the parse endpoint.
    """
    documents = DocumentService(_AppParser(request.app), slots, max_upload_mb=settings.max_upload_mb)
    return ExtractionService(
        repository,
        ParsingTextSource(documents, max_upload_mb=settings.max_upload_mb),
        TemplateServiceCatalog(templates),
        max_pending=settings.queue_max_pending,
        result_ttl=timedelta(hours=settings.result_ttl_hours),
    )
