"""Builds what a request needs from the objects the app owns."""

from typing import Annotated, cast

from fastapi import Depends, File, Request, UploadFile
from fastapi.exceptions import RequestValidationError

from formlens.config import Settings, get_settings
from formlens.parsing.exceptions import ModelUnavailable
from formlens.parsing.models import BYTES_PER_MB
from formlens.parsing.ports import DocumentParser
from formlens.parsing.service import DocumentService
from formlens.parsing.slots import ParseSlots
from formlens.query import REPEATED_PARAMETER


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


async def read_upload(
    request: Request,
    file: Annotated[
        UploadFile,
        File(
            description="The document: a PDF, PNG, JPEG or TIFF file. An empty file is refused with 400.",
            # Documents what the service enforces, so a generated "valid" request is never an empty file.
            json_schema_extra={"minLength": 1},
        ),
    ],
    settings: Annotated[Settings, Depends(get_settings)],
) -> bytes:
    """Read the upload, at most one byte more than the limit, so the service can tell it is too large.

    Starlette keeps only the last of several `file` parts and drops the rest without a word, so the
    request would mean something different from what its first part says. It is refused with 422, as
    a repeated query parameter is. The client's file name is never read: it could name a person or a case.
    """
    form = await request.form()  # already parsed for `file`; Starlette caches it on the request
    if len(form.getlist("file")) > 1:
        raise RequestValidationError(
            [
                {
                    "type": REPEATED_PARAMETER,
                    "loc": ("body", "file"),
                    "msg": "Send the file once.",
                    "input": None,
                }
            ]
        )
    return await file.read(settings.max_upload_mb * BYTES_PER_MB + 1)
