"""Constants shared by the example's modules."""

from typing import Final

from fastapi_szumplate.problems import ProblemType

API_PREFIX: Final = "/v1"

# Both modules answer with it, so it lives here instead of one module importing the other.
BOOK_NOT_FOUND: Final = ProblemType("book-not-found", "Book not found", 404)
