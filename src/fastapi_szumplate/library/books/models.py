"""The book entity. Plain data: the module has no rule beyond "an ISBN is unique"."""

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class Book:
    """A title the library owns. `copies` is the fixed capacity, never the stock left."""

    id: UUID
    isbn: str
    title: str
    author: str
    copies: int
