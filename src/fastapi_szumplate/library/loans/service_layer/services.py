"""The loans use cases: gather facts, ask the domain, save. Knows nothing of HTTP."""

import uuid
from collections.abc import Callable
from datetime import date
from uuid import UUID

import structlog

from fastapi_szumplate.library.loans.domain.exceptions import BookNotInCatalog, LoanNotFound
from fastapi_szumplate.library.loans.domain.model import Loan
from fastapi_szumplate.library.loans.domain.ports import BookCatalog, LoanRepository

log = structlog.get_logger(__name__)


class LoanService:
    """Lend books, return them and look loans up."""

    def __init__(
        self,
        loans: LoanRepository,
        catalog: BookCatalog,
        *,
        today: Callable[[], date],
        loan_days: int,
        max_active_per_member: int,
    ) -> None:
        """Wire the ports, the clock and the lending settings."""
        self._loans = loans
        self._catalog = catalog
        self._today = today
        self._loan_days = loan_days
        self._max_active = max_active_per_member

    def lend(self, *, book_id: UUID, member_id: str) -> Loan:
        """Lend a book; raises the first lending rule it breaks."""
        copies = self._catalog.copies_of(book_id)  # capacity never changes, so read it outside
        if copies is None:
            raise BookNotInCatalog(book_id)
        with self._loans.transaction():
            loan = Loan.lend(
                loan_id=uuid.uuid7(),
                book_id=book_id,
                member_id=member_id,
                today=self._today(),
                loan_days=self._loan_days,
                copies=copies,
                active_loans_of_book=self._loans.count_active_for_book(book_id),
                active_loans_of_member=self._loans.active_for_member(member_id),
                max_active_per_member=self._max_active,
            )
            self._loans.add(loan)
        log.info("loan_created", loan_id=str(loan.id), book_id=str(book_id), member_id=member_id)
        return loan

    def give_back(self, loan_id: UUID, *, returned_on: date | None) -> Loan:
        """Return a loan, by default today; raises if it is unknown or the rules refuse."""
        with self._loans.transaction():
            loan = self._loans.get(loan_id)
            if loan is None:
                raise LoanNotFound(loan_id)
            returned = loan.give_back(returned_on or self._today())
            self._loans.save(returned)
        log.info("loan_returned", loan_id=str(loan_id))
        return returned

    def get(self, loan_id: UUID) -> Loan:
        """Return a loan; raises `LoanNotFound` for an unknown id."""
        loan = self._loans.get(loan_id)
        if loan is None:
            raise LoanNotFound(loan_id)
        return loan

    def list_loans(
        self, *, member_id: str | None, active: bool | None, limit: int, offset: int
    ) -> tuple[list[Loan], int]:
        """Return one page of loans matching the filters, and the match count."""
        return self._loans.list_loans(member_id=member_id, active=active, limit=limit, offset=offset)
