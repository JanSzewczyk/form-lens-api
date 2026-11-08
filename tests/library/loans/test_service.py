from datetime import date
from uuid import UUID

import pytest

from fastapi_szumplate.library.loans.domain.exceptions import (
    AlreadyBorrowed,
    BookNotInCatalog,
    LoanAlreadyReturned,
    LoanNotFound,
    MemberLimitReached,
    NoFreeCopy,
)
from fastapi_szumplate.library.loans.domain.ports import LoanRepository
from fastapi_szumplate.library.loans.service_layer.services import LoanService
from tests.library.loans.conftest import FakeCatalog, make_service

BOOK_A = UUID(int=1)
BOOK_B = UUID(int=2)


@pytest.fixture
def service(loan_repository: LoanRepository) -> LoanService:
    return make_service(loan_repository, FakeCatalog({BOOK_A: 1, BOOK_B: 2}))


def test_lend_stores_a_loan_due_after_the_configured_days(service: LoanService) -> None:
    loan = service.lend(book_id=BOOK_A, member_id="member-1")

    assert service.get(loan.id) == loan
    assert (loan.borrowed_on, loan.due_on) == (date(2026, 1, 6), date(2026, 1, 20))


def test_lending_an_unknown_book_is_refused(service: LoanService) -> None:
    with pytest.raises(BookNotInCatalog, match=f"Book {UUID(int=404)} not found"):
        service.lend(book_id=UUID(int=404), member_id="member-1")


def test_lend_refuses_the_same_book_twice_to_one_member(service: LoanService) -> None:
    service.lend(book_id=BOOK_B, member_id="member-1")

    with pytest.raises(AlreadyBorrowed, match=f"Member member-1 already has book {BOOK_B} on loan"):
        service.lend(book_id=BOOK_B, member_id="member-1")


def test_lend_refuses_when_no_copy_is_free(service: LoanService) -> None:
    service.lend(book_id=BOOK_A, member_id="member-1")

    with pytest.raises(NoFreeCopy, match=f"No free copy of book {BOOK_A}"):
        service.lend(book_id=BOOK_A, member_id="member-2")


def test_lend_refuses_a_member_at_the_limit(loan_repository: LoanRepository) -> None:
    books = {UUID(int=n): 1 for n in range(10, 14)}
    service = make_service(loan_repository, FakeCatalog(books), max_active=3)
    for book_id in list(books)[:3]:
        service.lend(book_id=book_id, member_id="member-1")

    with pytest.raises(MemberLimitReached, match="Member member-1 already has 3 active loans"):
        service.lend(book_id=list(books)[3], member_id="member-1")


def test_returning_frees_the_copy_and_the_member_slot(service: LoanService) -> None:
    loan = service.lend(book_id=BOOK_A, member_id="member-1")

    service.give_back(loan.id, returned_on=None)

    assert service.lend(book_id=BOOK_A, member_id="member-2").book_id == BOOK_A


def test_return_defaults_to_today_and_accepts_a_date(service: LoanService) -> None:
    first = service.lend(book_id=BOOK_B, member_id="member-1")
    second = service.lend(book_id=BOOK_B, member_id="member-2")

    assert service.give_back(first.id, returned_on=None).returned_on == date(2026, 1, 6)
    assert service.give_back(second.id, returned_on=date(2026, 1, 9)).returned_on == date(2026, 1, 9)


def test_returning_twice_is_refused(service: LoanService) -> None:
    loan = service.lend(book_id=BOOK_A, member_id="member-1")
    service.give_back(loan.id, returned_on=None)

    with pytest.raises(LoanAlreadyReturned, match=f"Loan {loan.id} was already returned"):
        service.give_back(loan.id, returned_on=None)


def test_unknown_loan_is_not_found(service: LoanService) -> None:
    with pytest.raises(LoanNotFound, match=f"Loan {UUID(int=5)} not found"):
        service.get(UUID(int=5))
    with pytest.raises(LoanNotFound, match=f"Loan {UUID(int=5)} not found"):
        service.give_back(UUID(int=5), returned_on=None)


def test_list_filters_by_member_and_activity(service: LoanService) -> None:
    kept = service.lend(book_id=BOOK_B, member_id="member-1")
    back = service.lend(book_id=BOOK_A, member_id="member-1")
    service.lend(book_id=BOOK_B, member_id="member-2")
    service.give_back(back.id, returned_on=None)

    mine, total = service.list_loans(member_id="member-1", active=True, limit=10, offset=0)
    returned, _ = service.list_loans(member_id=None, active=False, limit=10, offset=0)
    everyone, everyone_total = service.list_loans(member_id=None, active=None, limit=2, offset=0)

    assert [loan.id for loan in mine] == [kept.id]
    assert total == 1
    assert [loan.id for loan in returned] == [back.id]
    assert len(everyone) == 2
    assert everyone_total == 3
