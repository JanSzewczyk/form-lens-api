"""HTTP routes of the loans module: parse, call one service method, shape the response."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query, Response, status

from fastapi_szumplate.library.constants import API_PREFIX, BOOK_NOT_FOUND
from fastapi_szumplate.library.loans.dependencies import get_loan_service
from fastapi_szumplate.library.loans.entrypoints.errors import (
    ALREADY_BORROWED,
    LOAN_ALREADY_RETURNED,
    LOAN_NOT_FOUND,
    MEMBER_LIMIT_REACHED,
    NO_FREE_COPY,
    RETURNED_BEFORE_BORROWED,
)
from fastapi_szumplate.library.loans.entrypoints.schemas import (
    LoanCreate,
    LoanPage,
    LoanResponse,
    LoanReturn,
)
from fastapi_szumplate.library.loans.service_layer.services import LoanService
from fastapi_szumplate.pagination import PageParams, get_page_params
from fastapi_szumplate.problems import VALIDATION_ERROR, malformed_body_response, problem_response

router = APIRouter(prefix=f"{API_PREFIX}/loans", tags=["loans"])

LoanId = Annotated[UUID, Path(description="Identifier of the loan.")]
Service = Annotated[LoanService, Depends(get_loan_service)]


@router.post(
    "",
    operation_id="create_loan",
    status_code=status.HTTP_201_CREATED,
    responses={
        201: {
            "description": "The book was lent.",
            "headers": {
                "Location": {
                    "description": "URL of the new loan.",
                    "schema": {"type": "string"},
                }
            },
            "links": {
                "GetLoan": {
                    "operationId": "get_loan",
                    "parameters": {"loan_id": "$response.body#/id"},
                    "description": "Fetch the loan that was just created.",
                },
                "ReturnLoan": {
                    "operationId": "return_loan",
                    "parameters": {"loan_id": "$response.body#/id"},
                    "description": "Return the book of the new loan.",
                },
            },
        },
        400: malformed_body_response(),
        404: problem_response(BOOK_NOT_FOUND),
        409: problem_response(ALREADY_BORROWED, MEMBER_LIMIT_REACHED, NO_FREE_COPY),
        422: problem_response(VALIDATION_ERROR),
    },
)
def create_loan(body: LoanCreate, response: Response, service: Service) -> LoanResponse:
    """Lend a book to a member.

    The loan is due after the configured number of days. A request the library state forbids is a
    409, checked in this order: the member already holds this book, the member is at the limit of
    active loans, no copy is free.
    """
    loan = service.lend(book_id=body.book_id, member_id=body.member_id)
    response.headers["Location"] = f"{API_PREFIX}/loans/{loan.id}"
    return LoanResponse.from_domain(loan)


@router.get(
    "",
    operation_id="list_loans",
    responses={422: problem_response(VALIDATION_ERROR)},
)
def list_loans(
    page: Annotated[PageParams, Depends(get_page_params)],
    service: Service,
    member_id: Annotated[
        str | None,
        Query(
            min_length=1,
            max_length=64,
            description="Only loans of this member.",
            examples=["member-42"],
        ),
    ] = None,
    active: Annotated[
        bool | None,
        Query(description="`true` for loans still out, `false` for returned ones."),
    ] = None,
) -> LoanPage:
    """List loans, oldest first, one page at a time, optionally for one member or only active."""
    loans, total = service.list_loans(member_id=member_id, active=active, limit=page.limit, offset=page.offset)
    return LoanPage(
        items=[LoanResponse.from_domain(loan) for loan in loans],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get(
    "/{loan_id}",
    operation_id="get_loan",
    responses={404: problem_response(LOAN_NOT_FOUND), 422: problem_response(VALIDATION_ERROR)},
)
def get_loan(loan_id: LoanId, service: Service) -> LoanResponse:
    """Fetch one loan by its id."""
    return LoanResponse.from_domain(service.get(loan_id))


@router.post(
    "/{loan_id}/return",
    operation_id="return_loan",
    responses={
        400: malformed_body_response(),
        404: problem_response(LOAN_NOT_FOUND),
        409: problem_response(LOAN_ALREADY_RETURNED, RETURNED_BEFORE_BORROWED),
        422: problem_response(VALIDATION_ERROR),
    },
)
def return_loan(loan_id: LoanId, service: Service, body: LoanReturn | None = None) -> LoanResponse:
    """Mark a loan as returned.

    Send no body to return it today, or a `returned_on` date. A loan can be returned once, and not
    before the day it was borrowed. A loan that was already returned is refused first
    (`loan-already-returned`), whatever `returned_on` says; only a loan still out is checked
    against the borrow date (`returned-before-borrowed`).
    """
    returned_on = body.returned_on if body else None
    return LoanResponse.from_domain(service.give_back(loan_id, returned_on=returned_on))
