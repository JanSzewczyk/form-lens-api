"""Builds the loans service for a request from the adapters the app owns."""

from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Annotated, cast

from fastapi import Depends, Request

from fastapi_szumplate.config import Settings, get_settings
from fastapi_szumplate.library.loans.domain.ports import BookCatalog, LoanRepository
from fastapi_szumplate.library.loans.service_layer.services import LoanService


def get_loan_repository(request: Request) -> LoanRepository:
    """Return the repository `include_library` stored on the app."""
    return cast("LoanRepository", request.app.state.loan_repository)


def get_book_catalog(request: Request) -> BookCatalog:
    """Return the catalog `include_library` stored on the app."""
    return cast("BookCatalog", request.app.state.book_catalog)


def get_today() -> Callable[[], date]:
    """Return the clock. Tests override this dependency to pin the date."""
    return lambda: datetime.now(UTC).date()


def get_loan_service(
    settings: Annotated[Settings, Depends(get_settings)],
    loans: Annotated[LoanRepository, Depends(get_loan_repository)],
    catalog: Annotated[BookCatalog, Depends(get_book_catalog)],
    today: Annotated[Callable[[], date], Depends(get_today)],
) -> LoanService:
    """Return the loans service."""
    return LoanService(
        loans,
        catalog,
        today=today,
        loan_days=settings.loan_days,
        max_active_per_member=settings.loans_max_active_per_member,
    )
