"""Parallel requests against the loan rules. Each test fails if its guard is removed."""

import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from fastapi_szumplate.library.loans.adapters.memory_repository import InMemoryLoanRepository
from fastapi_szumplate.library.loans.dependencies import get_loan_repository
from fastapi_szumplate.library.loans.domain.model import Loan
from fastapi_szumplate.library.loans.domain.ports import LoanRepository
from tests.library.factories import book_payload, isbn_for

PARALLEL = 8
ROUNDS = pytest.mark.parametrize("attempt", range(5), ids=lambda n: f"round-{n}")  # fresh app each
TYPE = "urn:problem:fastapi-szumplate:"

pytestmark = [pytest.mark.concurrency, pytest.mark.usefixtures("pinned_clock")]


class SlowReadsLoanRepository(InMemoryLoanRepository):
    """Pauses after each read so a check made outside the lock goes stale before the write."""

    def get(self, loan_id: UUID) -> Loan | None:
        loan = super().get(loan_id)
        time.sleep(0.01)
        return loan

    def active_for_member(self, member_id: str) -> list[Loan]:
        loans = super().active_for_member(member_id)
        time.sleep(0.01)
        return loans

    def count_active_for_book(self, book_id: UUID) -> int:
        count = super().count_active_for_book(book_id)
        time.sleep(0.01)
        return count


@pytest.fixture
def loans(app: FastAPI) -> LoanRepository:
    repository: LoanRepository = SlowReadsLoanRepository()
    app.dependency_overrides[get_loan_repository] = lambda: repository
    return repository


def add_book(app: FastAPI, number: int, *, copies: int = 1) -> str:
    response = TestClient(app).post("/v1/books", json=book_payload(isbn=isbn_for(number), copies=copies))
    return str(response.json()["id"])


def in_parallel(app: FastAPI, calls: list[Callable[[TestClient], Any]]) -> list[Any]:
    """Run every call in its own thread with its own client, released together."""
    barrier = threading.Barrier(len(calls), timeout=5)

    def run(call: Callable[[TestClient], Any]) -> Any:
        client = TestClient(app)
        barrier.wait()
        return call(client)

    with ThreadPoolExecutor(len(calls)) as pool:
        return list(pool.map(run, calls))


def lend(book_id: str, member_id: str) -> Callable[[TestClient], Any]:
    return lambda client: client.post("/v1/loans", json={"book_id": book_id, "member_id": member_id})


@ROUNDS
def test_the_last_copy_goes_to_one_of_eight_members(app: FastAPI, loans: LoanRepository, attempt: int) -> None:
    book_id = add_book(app, 1, copies=1)

    responses = in_parallel(app, [lend(book_id, f"member-{n}") for n in range(PARALLEL)])

    assert sorted(r.status_code for r in responses) == [201] + [409] * (PARALLEL - 1)
    assert {r.json()["type"] for r in responses if r.status_code == 409} == {f"{TYPE}no-free-copy"}
    assert loans.count_active_for_book(UUID(book_id)) == 1


@ROUNDS
def test_one_member_cannot_exceed_the_limit_with_eight_parallel_loans(
    app: FastAPI, loans: LoanRepository, attempt: int
) -> None:
    books = [add_book(app, n) for n in range(1, PARALLEL + 1)]

    responses = in_parallel(app, [lend(book_id, "member-1") for book_id in books])

    assert sorted(r.status_code for r in responses) == [201] * 3 + [409] * (PARALLEL - 3)
    assert {r.json()["type"] for r in responses if r.status_code == 409} == {f"{TYPE}member-limit-reached"}
    assert len(loans.active_for_member("member-1")) == 3


@ROUNDS
def test_the_same_member_and_book_in_eight_parallel_requests_make_one_loan(
    app: FastAPI, loans: LoanRepository, attempt: int
) -> None:
    book_id = add_book(app, 1, copies=PARALLEL)

    responses = in_parallel(app, [lend(book_id, "member-1") for _ in range(PARALLEL)])

    assert sorted(r.status_code for r in responses) == [201] + [409] * (PARALLEL - 1)
    assert {r.json()["type"] for r in responses if r.status_code == 409} == {f"{TYPE}already-borrowed"}
    assert len(loans.active_for_member("member-1")) == 1


@ROUNDS
def test_a_loan_is_returned_once_in_eight_parallel_returns(app: FastAPI, loans: LoanRepository, attempt: int) -> None:
    book_id = add_book(app, 1)
    loan_id = TestClient(app).post("/v1/loans", json={"book_id": book_id, "member_id": "member-1"}).json()["id"]

    responses = in_parallel(app, [lambda client: client.post(f"/v1/loans/{loan_id}/return")] * PARALLEL)

    assert sorted(r.status_code for r in responses) == [200] + [409] * (PARALLEL - 1)
    assert {r.json()["type"] for r in responses if r.status_code == 409} == {f"{TYPE}loan-already-returned"}
    assert loans.count_active_for_book(UUID(book_id)) == 0


@ROUNDS
def test_parallel_lendings_of_two_scarce_books_never_oversell_either(
    app: FastAPI, loans: LoanRepository, attempt: int
) -> None:
    first = add_book(app, 1, copies=2)
    second = add_book(app, 2, copies=3)
    calls = [lend(first, f"a-{n}") for n in range(PARALLEL)] + [lend(second, f"b-{n}") for n in range(PARALLEL)]

    responses = in_parallel(app, calls)

    by_book = {first: 2, second: 3}
    for book_id, copies in by_book.items():
        outcomes = [r.status_code for r in responses if r.status_code == 201 and r.json()["book_id"] == book_id]
        assert len(outcomes) == copies
        assert loans.count_active_for_book(UUID(book_id)) == copies
    assert sorted(r.status_code for r in responses) == [201] * 5 + [409] * (2 * PARALLEL - 5)
