from datetime import date, timedelta
from uuid import UUID

import pytest
from hypothesis import given
from hypothesis import strategies as st

from fastapi_szumplate.library.loans.domain.exceptions import (
    AlreadyBorrowed,
    LoanAlreadyReturned,
    MemberLimitReached,
    NoFreeCopy,
    ReturnedBeforeBorrowed,
)
from fastapi_szumplate.library.loans.domain.model import Loan
from tests.library.factories import LoanFactory

BOOK = UUID(int=1)
TODAY = date(2026, 1, 6)


def lend(
    *,
    active_of_member: list[Loan] | None = None,
    active_of_book: int = 0,
    copies: int = 1,
    max_active: int = 3,
    today: date = TODAY,
    loan_days: int = 14,
) -> Loan:
    return Loan.lend(
        loan_id=UUID(int=99),
        book_id=BOOK,
        member_id="member-1",
        today=today,
        loan_days=loan_days,
        copies=copies,
        active_loans_of_book=active_of_book,
        active_loans_of_member=active_of_member or [],
        max_active_per_member=max_active,
    )


def test_lending_sets_the_dates_and_leaves_the_loan_active() -> None:
    loan = lend()

    assert (loan.borrowed_on, loan.due_on) == (date(2026, 1, 6), date(2026, 1, 20))
    assert loan.is_active
    assert loan.returned_on is None


def test_member_cannot_borrow_a_book_they_already_hold() -> None:
    held = LoanFactory.build(book_id=BOOK)

    with pytest.raises(AlreadyBorrowed, match="member-1"):
        lend(active_of_member=[held])


def test_a_book_the_member_returned_can_be_borrowed_again() -> None:
    # Only active loans are passed to the rule, so a returned one is not in the list.
    assert lend(active_of_member=[]).book_id == BOOK


def test_member_at_the_limit_is_refused() -> None:
    held = LoanFactory.build_batch(3)

    with pytest.raises(MemberLimitReached, match="3 active loans"):
        lend(active_of_member=held, max_active=3)


def test_member_below_the_limit_is_served() -> None:
    held = LoanFactory.build_batch(2)

    assert lend(active_of_member=held, max_active=3).book_id == BOOK


def test_book_with_every_copy_out_is_refused() -> None:
    with pytest.raises(NoFreeCopy, match=f"No free copy of book {BOOK}"):
        lend(active_of_book=2, copies=2)


def test_book_with_a_free_copy_is_served() -> None:
    assert lend(active_of_book=1, copies=2).book_id == BOOK


def test_already_borrowed_wins_over_the_limit_and_the_stock() -> None:
    held = [LoanFactory.build(book_id=BOOK), *LoanFactory.build_batch(2)]

    with pytest.raises(AlreadyBorrowed, match=f"already has book {BOOK} on loan"):
        lend(active_of_member=held, max_active=3, active_of_book=1, copies=1)


def test_member_limit_wins_over_the_stock() -> None:
    held = LoanFactory.build_batch(3)

    with pytest.raises(MemberLimitReached, match="already has 3 active loans"):
        lend(active_of_member=held, max_active=3, active_of_book=1, copies=1)


def test_giving_back_records_the_day() -> None:
    loan = LoanFactory.build(borrowed_on=date(2026, 1, 6))

    returned = loan.give_back(date(2026, 1, 10))

    assert returned.returned_on == date(2026, 1, 10)
    assert not returned.is_active
    assert loan.is_active  # the original is untouched


def test_a_loan_can_be_returned_on_the_day_it_was_borrowed() -> None:
    loan = LoanFactory.build(borrowed_on=date(2026, 1, 6))

    assert loan.give_back(date(2026, 1, 6)).returned_on == date(2026, 1, 6)


def test_a_returned_loan_cannot_be_returned_again() -> None:
    loan = LoanFactory.build(returned_on=date(2026, 1, 8))

    with pytest.raises(LoanAlreadyReturned, match=f"Loan {loan.id} was already returned"):
        loan.give_back(date(2026, 1, 9))


def test_already_returned_wins_over_a_return_date_before_the_borrow_date() -> None:
    loan = LoanFactory.build(borrowed_on=date(2026, 1, 6), returned_on=date(2026, 1, 8))

    with pytest.raises(LoanAlreadyReturned, match=f"Loan {loan.id} was already returned"):
        loan.give_back(date(2026, 1, 1))


def test_return_before_the_borrow_date_is_refused() -> None:
    loan = LoanFactory.build(borrowed_on=date(2026, 1, 6))

    with pytest.raises(ReturnedBeforeBorrowed, match="2026-01-05"):
        loan.give_back(date(2026, 1, 5))


@given(
    today=st.dates(min_value=date(2000, 1, 1), max_value=date(2100, 12, 31)),
    loan_days=st.integers(min_value=1, max_value=365),
)
def test_due_date_is_exactly_loan_days_after_the_borrow_date(today: date, loan_days: int) -> None:
    loan = lend(today=today, loan_days=loan_days)

    assert loan.due_on - loan.borrowed_on == timedelta(days=loan_days)
    assert loan.give_back(loan.due_on).returned_on == loan.due_on
