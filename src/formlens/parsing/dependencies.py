"""Builds what a request needs from the objects the app owns."""

from typing import Annotated, cast

from fastapi import Depends, File, Request, UploadFile

from formlens.config import Settings, get_settings
from formlens.parsing.exceptions import ModelUnavailable
from formlens.parsing.ports import DocumentParser
from formlens.parsing.service import BYTES_PER_MB, DocumentService
from formlens.parsing.slots import ParseSlots


def get_parser(request: Request) -> DocumentParser:
    """Return the loaded parser; `ModelUnavailable` while the model is not loaded."""
    parser = cast("DocumentParser | None", request.app.state.parser)
    if parser is None:
        raise ModelUnavailable
    return parser


def get_slots(request: Request) -> ParseSlots:
    """Return the slots the running app was built with."""
    return cast("ParseSlots", request.app.state.parse_slots)


def get_document_service(
    parser: Annotated[DocumentParser, Depends(get_parser)],
    slots: Annotated[ParseSlots, Depends(get_slots)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> DocumentService:
    """Build the service for one request from the parser, the slots and the limit."""
    return DocumentService(parser, slots, max_upload_mb=settings.max_upload_mb)


def read_upload(
    file: Annotated[UploadFile, File(description="The document: a PDF, PNG, JPEG or TIFF file.")],
    settings: Annotated[Settings, Depends(get_settings)],
) -> bytes:
    """Read the upload, at most one byte more than the limit, so the service can tell it is too large.

    The client's file name is never read: it could name a person or a case.
    """
    return file.file.read(settings.max_upload_mb * BYTES_PER_MB + 1)
