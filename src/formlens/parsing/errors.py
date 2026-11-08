"""One problem type per domain error, and the mapping the app registers."""

from typing import Final

from formlens.parsing.exceptions import (
    FileTooLarge,
    InvalidFile,
    ModelUnavailable,
    ParseFailed,
    ParserBusy,
    UnsupportedMediaType,
)
from formlens.problems import ProblemType

INVALID_FILE: Final = ProblemType("invalid-file", "Invalid file", 400)
FILE_TOO_LARGE: Final = ProblemType("file-too-large", "File too large", 413)
UNSUPPORTED_MEDIA_TYPE: Final = ProblemType("unsupported-media-type", "Unsupported media type", 415)
PARSE_FAILED: Final = ProblemType("parse-failed", "Document could not be parsed", 500)
MODEL_UNAVAILABLE: Final = ProblemType("model-unavailable", "Model unavailable", 503)
PARSER_BUSY: Final = ProblemType("parser-busy", "Parser busy", 503)

ERRORS: Final[dict[type[Exception], ProblemType]] = {
    InvalidFile: INVALID_FILE,
    FileTooLarge: FILE_TOO_LARGE,
    UnsupportedMediaType: UNSUPPORTED_MEDIA_TYPE,
    ParseFailed: PARSE_FAILED,
    ModelUnavailable: MODEL_UNAVAILABLE,
    ParserBusy: PARSER_BUSY,
}
