"""What the loans service needs from the outside world."""

from contextlib import AbstractContextManager
from typing import Protocol
from uuid import UUID

from fastapi_szumplate.library.loans.domain.model import Loan


class LoanRepository(Protocol):
    """Where loans are kept. Every adapter must pass the shared contract suite."""

    def transaction(self) -> AbstractContextManager[None]:
        """Open an exclusive section: reads and writes inside it cannot interleave with another.

        A rule that reads loans before it writes one (a free copy, a member's limit) runs inside
        it. An SQL adapter locks the book row (`SELECT ... FOR UPDATE`) or the member instead.
        """
        ...

    def add(self, loan: Loan) -> None:
        """Store a new loan."""
        ...

    def get(self, loan_id: UUID) -> Loan | None:
        """Return the loan or `None`."""
        ...

    def save(self, loan: Loan) -> None:
        """Replace a stored loan."""
        ...

    def active_for_member(self, member_id: str) -> list[Loan]:
        """Return the member's loans that are still out."""
        ...

    def count_active_for_book(self, book_id: UUID) -> int:
        """Return how many copies of the book are out."""
        ...

    def list_loans(
        self, *, member_id: str | None, active: bool | None, limit: int, offset: int
    ) -> tuple[list[Loan], int]:
        """Return one page, oldest first, of loans matching the filters, and the match count."""
        ...


class BookCatalog(Protocol):
    """What loans needs to know about books: only the capacity."""

    def copies_of(self, book_id: UUID) -> int | None:
        """Return how many copies the library owns, or `None` for an unknown book."""
        ...
