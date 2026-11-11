"""The parsing endpoint."""

from typing import Annotated, Any, Final

from fastapi import APIRouter, Depends, Query

from formlens.parsing.dependencies import get_document_service, read_upload
from formlens.parsing.errors import (
    FILE_TOO_LARGE,
    INVALID_FILE,
    MODEL_UNAVAILABLE,
    PARSE_FAILED,
    PARSER_BUSY,
    UNSUPPORTED_MEDIA_TYPE,
)
from formlens.parsing.models import OutputFormat
from formlens.parsing.schemas import ParseResponse
from formlens.parsing.service import DocumentService
from formlens.problems import VALIDATION_ERROR, problem_response

PARSE_PATH: Final = "/v1/documents/parse"
DOCUMENTS_TAG: Final = {
    "name": "documents",
    "description": "Upload a document and read its text. The model runs on the server; nothing leaves it.",
}

router = APIRouter(prefix="/v1/documents", tags=["documents"])


def _unavailable() -> dict[str, Any]:
    """Document the 503 with the `Retry-After` header a busy parser sets."""
    response = problem_response(MODEL_UNAVAILABLE, PARSER_BUSY)
    response["headers"] = {
        "Retry-After": {
            "description": "Whole seconds to wait before trying again; set when the parser is busy.",
            "schema": {"type": "integer", "examples": [5]},
        }
    }
    return response


@router.post(
    "/parse",
    operation_id="parse_document",
    response_model=ParseResponse,
    responses={
        400: problem_response(
            INVALID_FILE,
            description=(
                "The file is empty or cannot be read (`invalid-file`), or the multipart body is malformed "
                "(`about:blank`)."
            ),
        ),
        413: problem_response(FILE_TOO_LARGE),
        415: problem_response(UNSUPPORTED_MEDIA_TYPE),
        422: problem_response(
            VALIDATION_ERROR,
            description=(
                "Request validation failed (`validation-error`): `file` is missing, is sent more than once "
                "or is a plain field; `format` is unknown."
            ),
        ),
        500: problem_response(PARSE_FAILED, description="The model failed or ran out of time (`parse-failed`)."),
        503: _unavailable(),
    },
)
def parse_document(
    service: Annotated[DocumentService, Depends(get_document_service)],
    content: Annotated[bytes, Depends(read_upload)],
    output_format: Annotated[
        OutputFormat,
        Query(alias="format", description="`markdown` keeps headings and tables; `text` is plain text."),
    ] = OutputFormat.MARKDOWN,
) -> ParseResponse:
    """Parse a document and return its text.

    Send the file as multipart form data in the `file` field. The type is read from the file's own
    bytes, not from its name or Content-Type. A busy parser answers 503 with a `Retry-After` header.
    """
    parsed = service.parse(content, output_format)
    return ParseResponse(
        text=parsed.text, page_count=parsed.page_count, elapsed_ms=parsed.elapsed_ms, model=parsed.model
    )
