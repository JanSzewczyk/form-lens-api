"""Errors the loan rules raise. They know nothing about HTTP."""

from datetime import date
from uuid import UUID


class LoanError(Exception):
    """Base class of every loans error."""


class LoanNotFound(LoanError):
    """No loan has this id."""

    def __init__(self, loan_id: UUID) -> None:
        """Remember which id was looked up."""
        super().__init__(f"Loan {loan_id} not found.")
        self.loan_id = loan_id


class BookNotInCatalog(LoanError):
    """The book to lend does not exist."""

    def __init__(self, book_id: UUID) -> None:
        """Remember which book was asked for."""
        super().__init__(f"Book {book_id} not found.")
        self.book_id = book_id


class AlreadyBorrowed(LoanError):
    """The member already holds an active loan of this book."""

    def __init__(self, member_id: str, book_id: UUID) -> None:
        """Remember who holds which book."""
        super().__init__(f"Member {member_id} already has book {book_id} on loan.")


class MemberLimitReached(LoanError):
    """The member holds as many active loans as allowed."""

    def __init__(self, member_id: str, limit: int) -> None:
        """Remember the member and the limit."""
        super().__init__(f"Member {member_id} already has {limit} active loans.")


class NoFreeCopy(LoanError):
    """Every copy of the book is on loan."""

    def __init__(self, book_id: UUID) -> None:
        """Remember the book."""
        super().__init__(f"No free copy of book {book_id}.")


class LoanAlreadyReturned(LoanError):
    """The loan was returned before."""

    def __init__(self, loan_id: UUID) -> None:
        """Remember the loan."""
        super().__init__(f"Loan {loan_id} was already returned.")


class ReturnedBeforeBorrowed(LoanError):
    """The return date is earlier than the borrow date."""

    def __init__(self, returned_on: date, borrowed_on: date) -> None:
        """Remember both dates."""
        super().__init__(f"Return date {returned_on} is before the borrow date {borrowed_on}.")
