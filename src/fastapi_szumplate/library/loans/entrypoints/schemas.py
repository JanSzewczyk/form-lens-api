"""Request and response schemas of the loans API."""

from datetime import date
from typing import Annotated, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from fastapi_szumplate.library.loans.domain.model import Loan
from fastapi_szumplate.pagination import Page
from fastapi_szumplate.types import IsoDate

MemberId = Annotated[
    str,
    Field(
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9._-]+$",
        description="Member identifier: letters, digits, dots, dashes or underscores, up to 64.",
        examples=["member-42"],
    ),
]


class LoanCreate(BaseModel):
    """Body of `POST /v1/loans`."""

    model_config = ConfigDict(extra="forbid")

    book_id: UUID = Field(description="Book to borrow.", examples=["0192f5e0-5a3b-7c11-9d2e-3f6a1b2c4d5e"])
    member_id: MemberId


class LoanReturn(BaseModel):
    """Optional body of `POST /v1/loans/{loan_id}/return`."""

    model_config = ConfigDict(extra="forbid")

    returned_on: IsoDate | None = Field(
        default=None,
        description="Day the book came back, `YYYY-MM-DD`. Defaults to today.",
        examples=["2026-01-20"],
    )


class LoanResponse(BaseModel):
    """A loan as the API shows it."""

    id: UUID = Field(
        description="Identifier assigned by the service.",
        examples=["0192f5e0-5a3b-7c11-9d2e-3f6a1b2c4d5e"],
    )
    book_id: UUID = Field(description="The borrowed book.", examples=["0192f5e0-5a3b-7c11-9d2e-3f6a1b2c4d5f"])
    member_id: MemberId
    borrowed_on: date = Field(description="Day the book was borrowed.", examples=["2026-01-06"])
    due_on: date = Field(description="Day the book is due back.", examples=["2026-01-20"])
    returned_on: date | None = Field(
        default=None,
        description="Day the book came back; `null` while it is still out.",
        examples=["2026-01-18"],
    )

    @classmethod
    def from_domain(cls, loan: Loan) -> Self:
        """Build the response from the domain object."""
        return cls(
            id=loan.id,
            book_id=loan.book_id,
            member_id=loan.member_id,
            borrowed_on=loan.borrowed_on,
            due_on=loan.due_on,
            returned_on=loan.returned_on,
        )


class LoanPage(Page[LoanResponse]):
    """One page of loans."""
