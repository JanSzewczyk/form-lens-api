"""The books port and its in-memory adapter."""

import threading
from typing import Protocol
from uuid import UUID

from fastapi_szumplate.library.books.exceptions import BookNotFound, IsbnAlreadyExists
from fastapi_szumplate.library.books.models import Book


class BookRepository(Protocol):
    """Where books are kept. Every adapter must pass the shared contract suite."""

    def add(self, book: Book) -> None:
        """Store a new book; raise `IsbnAlreadyExists` if the ISBN is taken, atomically."""
        ...

    def get(self, book_id: UUID) -> Book | None:
        """Return the book or `None`."""
        ...

    def list_page(self, *, limit: int, offset: int) -> tuple[list[Book], int]:
        """Return one page, oldest first, and the total number of books."""
        ...

    def update(self, book: Book) -> None:
        """Replace a stored book; raise `BookNotFound` if the id is unknown."""
        ...


class InMemoryBookRepository:
    """Books in a dict. The lock makes "ISBN free? then insert" one step."""

    def __init__(self) -> None:
        """Start empty."""
        self._books: dict[UUID, Book] = {}
        self._isbns: set[str] = set()
        self._lock = threading.RLock()

    def _isbn_taken(self, isbn: str) -> bool:
        return isbn in self._isbns

    def add(self, book: Book) -> None:
        """Store a new book; raise `IsbnAlreadyExists` if the ISBN is taken."""
        with self._lock:
            if self._isbn_taken(book.isbn):
                raise IsbnAlreadyExists(book.isbn)
            self._books[book.id] = book
            self._isbns.add(book.isbn)

    def get(self, book_id: UUID) -> Book | None:
        """Return the book or `None`."""
        with self._lock:
            return self._books.get(book_id)

    def list_page(self, *, limit: int, offset: int) -> tuple[list[Book], int]:
        """Return one page, oldest first, and the total number of books."""
        with self._lock:
            books = list(self._books.values())
        return books[offset : offset + limit], len(books)

    def update(self, book: Book) -> None:
        """Replace a stored book; raise `BookNotFound` if the id is unknown."""
        with self._lock:
            if book.id not in self._books:
                raise BookNotFound(book.id)
            self._books[book.id] = book
