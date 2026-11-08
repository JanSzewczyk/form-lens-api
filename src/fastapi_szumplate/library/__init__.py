"""The example domain: a small library (books and, later, loans).

Everything the example needs lives under this package and `tests/library/`. To remove it, delete
both folders and the `include_library(app)` call in `main.py`; see
`docs/how-to/remove-the-example.md`. Nothing outside this package may import it except `main.py`.
"""

from fastapi import FastAPI

from fastapi_szumplate.library.books.errors import ERRORS as BOOK_ERRORS
from fastapi_szumplate.library.books.repository import InMemoryBookRepository
from fastapi_szumplate.library.books.router import router as books_router
from fastapi_szumplate.library.loans.adapters.books_catalog import RepositoryBookCatalog
from fastapi_szumplate.library.loans.adapters.memory_repository import InMemoryLoanRepository
from fastapi_szumplate.library.loans.entrypoints.errors import ERRORS as LOAN_ERRORS
from fastapi_szumplate.library.loans.entrypoints.router import router as loans_router
from fastapi_szumplate.openapi import add_tags
from fastapi_szumplate.problems import register_domain_errors

TAGS = [
    {"name": "books", "description": "The catalogue. Books have a fixed number of copies."},
    {"name": "loans", "description": "Lending books to members and taking them back."},
]


def include_library(app: FastAPI) -> None:
    """Build the example's adapters once, store them on the app and mount its routes."""
    books = InMemoryBookRepository()
    app.state.book_repository = books
    app.state.loan_repository = InMemoryLoanRepository()
    app.state.book_catalog = RepositoryBookCatalog(books)

    add_tags(app, *TAGS)
    register_domain_errors(app, BOOK_ERRORS)
    register_domain_errors(app, LOAN_ERRORS)
    app.include_router(books_router)
    app.include_router(loans_router)
