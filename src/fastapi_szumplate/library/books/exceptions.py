"""Errors of the books module. They know nothing about HTTP."""

from uuid import UUID


class BookError(Exception):
    """Base class of every books error."""


class BookNotFound(BookError):
    """No book has this id."""

    def __init__(self, book_id: UUID) -> None:
        """Remember which id was looked up."""
        super().__init__(f"Book {book_id} not found.")
        self.book_id = book_id


class IsbnAlreadyExists(BookError):
    """Another book already uses this ISBN."""

    def __init__(self, isbn: str) -> None:
        """Remember the duplicated ISBN."""
        super().__init__(f"A book with ISBN {isbn} already exists.")
        self.isbn = isbn
