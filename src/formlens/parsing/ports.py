"""What the service needs from the outside: a parser that turns document bytes into text."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from formlens.config import Settings


@dataclass(frozen=True, slots=True)
class ParseResult:
    """What a parser returns: the text in both forms, the page count, the time and the model used."""

    text: str
    plain_text: str
    page_count: int
    elapsed_ms: int
    model_id: str


class DocumentParser(Protocol):
    """Turns the bytes of a document into text.

    `filename` is the neutral name the service chose (`upload.pdf`), never the client's. An adapter
    raises `InvalidFile` for bytes it cannot read and `ParseFailed` for any other failure.
    """

    def parse(self, content: bytes, filename: str) -> ParseResult:
        """Parse one document."""
        ...


type ParserFactory = Callable[[Settings], DocumentParser]
"""Builds the parser once at startup; it may load a model, so it runs in a worker thread."""
