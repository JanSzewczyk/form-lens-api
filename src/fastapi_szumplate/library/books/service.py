"""Use cases of the books module."""

import uuid
from dataclasses import replace
from uuid import UUID

import structlog

from fastapi_szumplate.library.books.exceptions import BookNotFound
from fastapi_szumplate.library.books.models import Book
from fastapi_szumplate.library.books.repository import BookRepository

log = structlog.get_logger(__name__)


class BookService:
    """Create, read and update books. Knows nothing of HTTP."""

    def __init__(self, books: BookRepository) -> None:
        """Use the given repository."""
        self._books = books

    def create(self, *, isbn: str, title: str, author: str, copies: int) -> Book:
        """Add a book; raises `IsbnAlreadyExists` when the ISBN is taken."""
        book = Book(id=uuid.uuid7(), isbn=isbn, title=title, author=author, copies=copies)
        self._books.add(book)
        log.info("book_created", book_id=str(book.id), copies=copies)
        return book

    def get(self, book_id: UUID) -> Book:
        """Return a book; raises `BookNotFound` for an unknown id."""
        book = self._books.get(book_id)
        if book is None:
            raise BookNotFound(book_id)
        return book

    def list_page(self, *, limit: int, offset: int) -> tuple[list[Book], int]:
        """Return one page of books and the total."""
        return self._books.list_page(limit=limit, offset=offset)

    def update(self, book_id: UUID, *, title: str, author: str) -> Book:
        """Change the title and author; the ISBN and the capacity never change."""
        updated = replace(self.get(book_id), title=title, author=author)
        self._books.update(updated)
        return updated
