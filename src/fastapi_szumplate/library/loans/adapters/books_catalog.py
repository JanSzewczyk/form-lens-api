"""The only place loans reaches into books: it answers "how many copies?" and nothing more."""

from uuid import UUID

from fastapi_szumplate.library.books.repository import BookRepository


class RepositoryBookCatalog:
    """Reads a book's capacity from the books repository and returns a plain `int`."""

    def __init__(self, books: BookRepository) -> None:
        """Read from the given books repository."""
        self._books = books

    def copies_of(self, book_id: UUID) -> int | None:
        """Return how many copies the library owns, or `None` for an unknown book."""
        book = self._books.get(book_id)
        return None if book is None else book.copies
