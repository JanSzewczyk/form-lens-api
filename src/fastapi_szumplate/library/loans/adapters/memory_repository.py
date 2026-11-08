"""Loans kept in a dict, guarded by one lock."""

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from uuid import UUID

from fastapi_szumplate.library.loans.domain.model import Loan


class InMemoryLoanRepository:
    """Loans in a dict. `transaction()` takes the lock, so "check, then write" is one step.

    The lock is re-entrant: the methods lock again inside a transaction. There is no rollback;
    the domain checks every rule before the one write that follows.
    """

    def __init__(self) -> None:
        """Start empty."""
        self._loans: dict[UUID, Loan] = {}
        self._lock = threading.RLock()

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """Hold the lock for the whole section."""
        with self._lock:
            yield

    def add(self, loan: Loan) -> None:
        """Store a new loan."""
        with self._lock:
            self._loans[loan.id] = loan

    def get(self, loan_id: UUID) -> Loan | None:
        """Return the loan or `None`."""
        with self._lock:
            return self._loans.get(loan_id)

    def save(self, loan: Loan) -> None:
        """Replace a stored loan."""
        with self._lock:
            self._loans[loan.id] = loan

    def active_for_member(self, member_id: str) -> list[Loan]:
        """Return the member's loans that are still out."""
        with self._lock:
            return [loan for loan in self._loans.values() if loan.member_id == member_id and loan.is_active]

    def count_active_for_book(self, book_id: UUID) -> int:
        """Return how many copies of the book are out."""
        with self._lock:
            return sum(1 for loan in self._loans.values() if loan.book_id == book_id and loan.is_active)

    def list_loans(
        self, *, member_id: str | None, active: bool | None, limit: int, offset: int
    ) -> tuple[list[Loan], int]:
        """Return one page, oldest first, of loans matching the filters, and the match count."""
        with self._lock:
            matching = [
                loan
                for loan in self._loans.values()
                if (member_id is None or loan.member_id == member_id) and (active is None or loan.is_active == active)
            ]
        return matching[offset : offset + limit], len(matching)
