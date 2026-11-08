import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from fastapi_szumplate.library.books.dependencies import get_book_repository
from fastapi_szumplate.library.books.repository import BookRepository, InMemoryBookRepository
from tests.library.factories import book_payload, isbn_for

PARALLEL = 8
ROUNDS = pytest.mark.parametrize("attempt", range(5), ids=lambda n: f"round-{n}")  # fresh app each


class SlowIsbnCheckRepository(InMemoryBookRepository):
    """Widens the window between "is the ISBN free?" and the insert so a missing guard shows."""

    def _isbn_taken(self, isbn: str) -> bool:
        taken = super()._isbn_taken(isbn)
        time.sleep(0.01)
        return taken


@pytest.fixture
def slow_books(app: FastAPI) -> BookRepository:
    repository: BookRepository = SlowIsbnCheckRepository()
    app.dependency_overrides[get_book_repository] = lambda: repository
    return repository


@pytest.mark.concurrency
@ROUNDS
def test_only_one_of_eight_parallel_posts_with_the_same_isbn_is_created(
    app: FastAPI, slow_books: BookRepository, attempt: int
) -> None:
    barrier = threading.Barrier(PARALLEL, timeout=5)

    def post(_: int) -> int:
        client = TestClient(app)  # one client per thread
        barrier.wait()
        return client.post("/v1/books", json=book_payload(isbn=isbn_for(1))).status_code

    with ThreadPoolExecutor(PARALLEL) as pool:
        statuses = list(pool.map(post, range(PARALLEL)))

    assert sorted(statuses) == [201] + [409] * (PARALLEL - 1)
    assert slow_books.list_page(limit=100, offset=0)[1] == 1


@pytest.mark.concurrency
@ROUNDS
def test_two_isbns_raced_by_sixteen_requests_create_exactly_two_books(
    app: FastAPI, slow_books: BookRepository, attempt: int
) -> None:
    barrier = threading.Barrier(2 * PARALLEL, timeout=5)

    def post(number: int) -> tuple[int, int]:
        client = TestClient(app)
        barrier.wait()
        isbn = isbn_for(number % 2 + 1)
        return number % 2, client.post("/v1/books", json=book_payload(isbn=isbn)).status_code

    with ThreadPoolExecutor(2 * PARALLEL) as pool:
        results = list(pool.map(post, range(2 * PARALLEL)))

    for isbn_index in (0, 1):
        assert sorted(code for index, code in results if index == isbn_index) == [201] + [409] * (PARALLEL - 1)
    assert slow_books.list_page(limit=100, offset=0)[1] == 2
