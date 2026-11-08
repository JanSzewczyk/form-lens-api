"""Maps the books errors to their Problem Details types."""

from fastapi_szumplate.library.books.exceptions import BookNotFound, IsbnAlreadyExists
from fastapi_szumplate.library.constants import BOOK_NOT_FOUND
from fastapi_szumplate.problems import ProblemType

ISBN_ALREADY_EXISTS = ProblemType("isbn-already-exists", "ISBN already exists", 409)

ERRORS: dict[type[Exception], ProblemType] = {
    BookNotFound: BOOK_NOT_FOUND,
    IsbnAlreadyExists: ISBN_ALREADY_EXISTS,
}
