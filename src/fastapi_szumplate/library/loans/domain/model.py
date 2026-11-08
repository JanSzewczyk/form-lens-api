"""The loan and the rules about lending and returning."""

from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date, timedelta
from typing import Self
from uuid import UUID

from fastapi_szumplate.library.loans.domain.exceptions import (
    AlreadyBorrowed,
    LoanAlreadyReturned,
    MemberLimitReached,
    NoFreeCopy,
    ReturnedBeforeBorrowed,
)


@dataclass(frozen=True, slots=True)
class Loan:
    """One book lent to one member."""

    id: UUID
    book_id: UUID
    member_id: str
    borrowed_on: date
    due_on: date
    returned_on: date | None = None

    @property
    def is_active(self) -> bool:
        """Return whether the book is still out."""
        return self.returned_on is None

    @classmethod
    def lend(
        cls,
        *,
        loan_id: UUID,
        book_id: UUID,
        member_id: str,
        today: date,
        loan_days: int,
        copies: int,
        active_loans_of_book: int,
        active_loans_of_member: Sequence[Self],
        max_active_per_member: int,
    ) -> Self:
        """Lend a book, or raise the first rule it breaks.

        The rules are checked in this order: the member already holds this book, the member is at
        the limit, no copy is free.
        """
        if any(loan.book_id == book_id for loan in active_loans_of_member):
            raise AlreadyBorrowed(member_id, book_id)
        if len(active_loans_of_member) >= max_active_per_member:
            raise MemberLimitReached(member_id, max_active_per_member)
        if active_loans_of_book >= copies:
            raise NoFreeCopy(book_id)
        return cls(
            id=loan_id,
            book_id=book_id,
            member_id=member_id,
            borrowed_on=today,
            due_on=today + timedelta(days=loan_days),
        )

    def give_back(self, returned_on: date) -> Self:
        """Return the loan on the given date, or raise the rule it breaks.

        A loan that was already returned is refused first, whatever the date; only a loan still
        out is checked against the borrow date.
        """
        if self.returned_on is not None:
            raise LoanAlreadyReturned(self.id)
        if returned_on < self.borrowed_on:
            raise ReturnedBeforeBorrowed(returned_on, self.borrowed_on)
        return replace(self, returned_on=returned_on)
