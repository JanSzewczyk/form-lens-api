"""Request and response schemas of the books API."""

from typing import Annotated, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from fastapi_szumplate.library.books.models import Book
from fastapi_szumplate.pagination import Page
from fastapi_szumplate.types import WholeNumber

Isbn = Annotated[
    str,
    Field(
        pattern=r"^[0-9]{13}$",  # not \d: Pydantic's regex engine reads \d as any Unicode digit
        description="ISBN-13, thirteen digits without hyphens. Unique across the catalogue.",
        examples=["9780132350884"],
    ),
]
# One character that is not whitespace. Pydantic strips surrounding whitespace with Rust's
# `trim()`, i.e. Unicode White_Space, so this class spells out exactly that set: `\s` is not the
# same set in Python, ECMAScript and Rust (U+0085 is `\s` in Python only, U+FEFF in ECMAScript
# only), and a client that reads the schema must agree with the server on what "blank" means.
NON_BLANK = r"[^\x09-\x0d \x85\xa0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]"
Title = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=200, pattern=NON_BLANK),
    Field(description="Title of the book.", examples=["Clean Code"]),
]
Author = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=200, pattern=NON_BLANK),
    Field(description="Author of the book.", examples=["Robert C. Martin"]),
]


class BookCreate(BaseModel):
    """Body of `POST /v1/books`."""

    model_config = ConfigDict(extra="forbid")

    isbn: Isbn
    title: Title
    author: Author
    copies: WholeNumber = Field(
        ge=1,
        le=1000,
        description="How many copies the library owns. Fixed once the book is created.",
        examples=[3],
    )


class BookUpdate(BaseModel):
    """Body of `PUT /v1/books/{book_id}`. The ISBN and the capacity cannot change."""

    model_config = ConfigDict(extra="forbid")

    title: Title
    author: Author


class BookResponse(BaseModel):
    """A book as the API shows it."""

    id: UUID = Field(
        description="Identifier assigned by the service.",
        examples=["0192f5e0-5a3b-7c11-9d2e-3f6a1b2c4d5e"],
    )
    isbn: Isbn
    title: Title
    author: Author
    copies: int = Field(description="How many copies the library owns.", examples=[3])

    @classmethod
    def from_domain(cls, book: Book) -> Self:
        """Build the response from the domain object."""
        return cls(id=book.id, isbn=book.isbn, title=book.title, author=book.author, copies=book.copies)


class BookPage(Page[BookResponse]):
    """One page of books."""
