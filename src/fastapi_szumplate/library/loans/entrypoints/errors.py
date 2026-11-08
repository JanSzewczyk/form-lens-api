"""Maps the loan errors to their Problem Details types."""

from fastapi_szumplate.library.constants import BOOK_NOT_FOUND
from fastapi_szumplate.library.loans.domain.exceptions import (
    AlreadyBorrowed,
    BookNotInCatalog,
    LoanAlreadyReturned,
    LoanNotFound,
    MemberLimitReached,
    NoFreeCopy,
    ReturnedBeforeBorrowed,
)
from fastapi_szumplate.problems import ProblemType

LOAN_NOT_FOUND = ProblemType("loan-not-found", "Loan not found", 404)
ALREADY_BORROWED = ProblemType("already-borrowed", "Member already has this book", 409)
MEMBER_LIMIT_REACHED = ProblemType("member-limit-reached", "Member loan limit reached", 409)
NO_FREE_COPY = ProblemType("no-free-copy", "No free copy", 409)
LOAN_ALREADY_RETURNED = ProblemType("loan-already-returned", "Loan already returned", 409)
RETURNED_BEFORE_BORROWED = ProblemType("returned-before-borrowed", "Returned before it was borrowed", 409)

ERRORS: dict[type[Exception], ProblemType] = {
    LoanNotFound: LOAN_NOT_FOUND,
    BookNotInCatalog: BOOK_NOT_FOUND,
    AlreadyBorrowed: ALREADY_BORROWED,
    MemberLimitReached: MEMBER_LIMIT_REACHED,
    NoFreeCopy: NO_FREE_COPY,
    LoanAlreadyReturned: LOAN_ALREADY_RETURNED,
    ReturnedBeforeBorrowed: RETURNED_BEFORE_BORROWED,
}
