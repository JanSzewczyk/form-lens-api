"""Fixtures of the loans tests: a pinned clock and a typed fake catalog."""

from datetime import date
from uuid import UUID

import pytest
from fastapi import FastAPI

from fastapi_szumplate.library.loans.adapters.memory_repository import InMemoryLoanRepository
from fastapi_szumplate.library.loans.dependencies import get_today
from fastapi_szumplate.library.loans.domain.ports import BookCatalog, LoanRepository
from fastapi_szumplate.library.loans.service_layer.services import LoanService

TODAY = date(2026, 1, 6)


class FakeCatalog:
    """Capacities by book id; an unknown id is not in the catalog."""

    def __init__(self, copies: dict[UUID, int]) -> None:
        self.copies = copies

    def copies_of(self, book_id: UUID) -> int | None:
        return self.copies.get(book_id)


@pytest.fixture
def today() -> date:
    return TODAY


@pytest.fixture(autouse=False)
def pinned_clock(app: FastAPI, today: date) -> None:
    """Make the app's clock return a fixed day."""
    app.dependency_overrides[get_today] = lambda: lambda: today


@pytest.fixture
def loan_repository() -> LoanRepository:
    return InMemoryLoanRepository()


@pytest.fixture
def catalog() -> BookCatalog:
    return FakeCatalog({})


def make_service(
    loans: LoanRepository, catalog: BookCatalog, *, today: date = TODAY, max_active: int = 3
) -> LoanService:
    return LoanService(loans, catalog, today=lambda: today, loan_days=14, max_active_per_member=max_active)
