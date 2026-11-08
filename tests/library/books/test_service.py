from uuid import UUID

import pytest

from fastapi_szumplate.library.books.exceptions import BookNotFound, IsbnAlreadyExists
from fastapi_szumplate.library.books.repository import BookRepository
from fastapi_szumplate.library.books.service import BookService
from tests.library.factories import isbn_for


@pytest.fixture
def service(book_repository: BookRepository) -> BookService:
    return BookService(book_repository)


def create(service: BookService, number: int = 1, *, copies: int = 2) -> UUID:
    return service.create(isbn=isbn_for(number), title="Title", author="Author", copies=copies).id


def test_create_stores_the_book_with_the_given_values(service: BookService) -> None:
    book = service.create(isbn=isbn_for(1), title="Clean Code", author="R. Martin", copies=4)

    assert service.get(book.id) == book
    assert (book.isbn, book.title, book.author, book.copies) == (
        isbn_for(1),
        "Clean Code",
        "R. Martin",
        4,
    )


def test_create_with_a_taken_isbn_is_refused(service: BookService) -> None:
    create(service, 1)

    with pytest.raises(IsbnAlreadyExists, match=isbn_for(1)):
        create(service, 1)


def test_get_unknown_book_raises_not_found(service: BookService) -> None:
    missing = UUID(int=1)

    with pytest.raises(BookNotFound, match=str(missing)):
        service.get(missing)


def test_update_changes_title_and_author_but_keeps_isbn_and_capacity(service: BookService) -> None:
    book_id = create(service, 1, copies=5)

    updated = service.update(book_id, title="New", author="Someone")

    assert (updated.title, updated.author) == ("New", "Someone")
    assert (updated.isbn, updated.copies) == (isbn_for(1), 5)
    assert service.get(book_id) == updated


def test_update_unknown_book_raises_not_found(service: BookService) -> None:
    with pytest.raises(BookNotFound, match=f"Book {UUID(int=2)} not found"):
        service.update(UUID(int=2), title="T", author="A")


def test_list_page_slices_in_creation_order_and_reports_the_total(service: BookService) -> None:
    ids = [create(service, n) for n in range(1, 6)]

    books, total = service.list_page(limit=2, offset=1)

    assert [b.id for b in books] == ids[1:3]
    assert total == 5
