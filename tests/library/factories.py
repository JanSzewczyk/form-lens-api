"""Factories for the example domain's test data. Set every value a test asserts on explicitly."""

import uuid
from datetime import date
from typing import Any

from factory.base import Factory
from factory.declarations import Sequence
from factory.faker import Faker

from fastapi_szumplate.library.books.models import Book
from fastapi_szumplate.library.loans.domain.model import Loan


def isbn_for(number: int) -> str:
    """Return a distinct 13-digit ISBN-shaped string for a sequence number."""
    return f"978{number:010d}"


class BookFactory(Factory[Book]):
    """Domain `Book`; ids and ISBNs are unique per call."""

    class Meta:
        model = Book

    id = Sequence(lambda _: uuid.uuid7())  # type: ignore[no-untyped-call]  # factory_boy declarations are untyped
    isbn = Sequence(isbn_for)  # type: ignore[no-untyped-call]  # factory_boy declarations are untyped
    title = Faker("sentence", nb_words=3)  # type: ignore[no-untyped-call]  # factory_boy declarations are untyped
    author = Faker("name")  # type: ignore[no-untyped-call]  # factory_boy declarations are untyped
    copies = 1


def book_payload(**overrides: Any) -> dict[str, Any]:
    """JSON body for `POST /v1/books`; override what the test asserts on."""
    book = BookFactory.build()
    body: dict[str, Any] = {
        "isbn": book.isbn,
        "title": book.title,
        "author": book.author,
        "copies": book.copies,
    }
    return {**body, **overrides}


class LoanFactory(Factory[Loan]):
    """Domain `Loan`: borrowed on a fixed day and still out. Override what a test asserts on."""

    class Meta:
        model = Loan

    id = Sequence(lambda _: uuid.uuid7())  # type: ignore[no-untyped-call]  # factory_boy declarations are untyped
    book_id = Sequence(lambda _: uuid.uuid7())  # type: ignore[no-untyped-call]  # factory_boy declarations are untyped
    member_id = Sequence(lambda n: f"member-{n}")  # type: ignore[no-untyped-call]  # factory_boy declarations are untyped
    borrowed_on = date(2026, 1, 6)
    due_on = date(2026, 1, 20)
    returned_on = None
