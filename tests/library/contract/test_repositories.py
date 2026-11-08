"""Repository contract: a new adapter (SQL, say) passes it by subclassing and providing `repo`."""

from datetime import date
from uuid import UUID

import pytest

from fastapi_szumplate.library.books.exceptions import BookNotFound, IsbnAlreadyExists
from fastapi_szumplate.library.books.repository import BookRepository, InMemoryBookRepository
from fastapi_szumplate.library.loans.adapters.memory_repository import InMemoryLoanRepository
from fastapi_szumplate.library.loans.domain.ports import LoanRepository
from tests.library.factories import BookFactory, LoanFactory, isbn_for


class BookRepositoryContract:
    """Behaviour every `BookRepository` adapter must have."""

    @pytest.fixture
    def repo(self) -> BookRepository:
        raise NotImplementedError

    def test_added_book_can_be_read_back(self, repo: BookRepository) -> None:
        book = BookFactory.build(title="Clean Code")

        repo.add(book)

        assert repo.get(book.id) == book

    def test_unknown_id_returns_none(self, repo: BookRepository) -> None:
        assert repo.get(UUID(int=7)) is None

    def test_second_book_with_the_same_isbn_is_refused(self, repo: BookRepository) -> None:
        repo.add(BookFactory.build(isbn=isbn_for(1)))

        with pytest.raises(IsbnAlreadyExists, match=f"ISBN {isbn_for(1)} already exists"):
            repo.add(BookFactory.build(isbn=isbn_for(1)))

    def test_a_refused_book_is_not_stored(self, repo: BookRepository) -> None:
        repo.add(BookFactory.build(isbn=isbn_for(1)))
        refused = BookFactory.build(isbn=isbn_for(1))
        with pytest.raises(IsbnAlreadyExists, match=f"ISBN {isbn_for(1)} already exists"):
            repo.add(refused)

        assert repo.get(refused.id) is None

    def test_update_replaces_the_stored_book(self, repo: BookRepository) -> None:
        book = BookFactory.build(title="Old")
        repo.add(book)
        changed = BookFactory.build(id=book.id, isbn=book.isbn, title="New")

        repo.update(changed)

        assert repo.get(book.id) == changed

    def test_update_of_an_unknown_book_is_refused(self, repo: BookRepository) -> None:
        unknown = BookFactory.build()

        with pytest.raises(BookNotFound, match=f"Book {unknown.id} not found"):
            repo.update(unknown)

    def test_pages_keep_insertion_order_and_report_the_total(self, repo: BookRepository) -> None:
        books = BookFactory.build_batch(5)
        for book in books:
            repo.add(book)

        first, total = repo.list_page(limit=2, offset=0)
        last, _ = repo.list_page(limit=2, offset=4)
        beyond, _ = repo.list_page(limit=2, offset=10)

        assert first == books[:2]
        assert last == books[4:]
        assert beyond == []
        assert total == 5


class TestInMemoryBookRepository(BookRepositoryContract):
    @pytest.fixture
    def repo(self) -> BookRepository:
        return InMemoryBookRepository()


class LoanRepositoryContract:
    """Behaviour every `LoanRepository` adapter must have."""

    @pytest.fixture
    def repo(self) -> LoanRepository:
        raise NotImplementedError

    def test_added_loan_can_be_read_back(self, repo: LoanRepository) -> None:
        loan = LoanFactory.build(member_id="member-1")

        repo.add(loan)

        assert repo.get(loan.id) == loan

    def test_unknown_id_returns_none(self, repo: LoanRepository) -> None:
        assert repo.get(UUID(int=7)) is None

    def test_save_replaces_the_stored_loan(self, repo: LoanRepository) -> None:
        loan = LoanFactory.build()
        repo.add(loan)
        returned = loan.give_back(date(2026, 1, 8))

        repo.save(returned)

        assert repo.get(loan.id) == returned

    def test_active_loans_are_counted_per_book_and_per_member(self, repo: LoanRepository) -> None:
        book = UUID(int=1)
        repo.add(LoanFactory.build(book_id=book, member_id="a"))
        repo.add(LoanFactory.build(book_id=book, member_id="b"))
        repo.add(LoanFactory.build(book_id=book, member_id="a", returned_on=date(2026, 1, 8)))
        repo.add(LoanFactory.build(book_id=UUID(int=2), member_id="a"))

        assert repo.count_active_for_book(book) == 2
        assert len(repo.active_for_member("a")) == 2
        assert repo.active_for_member("nobody") == []

    def test_list_filters_and_pages_in_insertion_order(self, repo: LoanRepository) -> None:
        loans = [
            LoanFactory.build(member_id="a"),
            LoanFactory.build(member_id="b"),
            LoanFactory.build(member_id="a", returned_on=date(2026, 1, 8)),
        ]
        for loan in loans:
            repo.add(loan)

        everything, total = repo.list_loans(member_id=None, active=None, limit=2, offset=0)
        mine, mine_total = repo.list_loans(member_id="a", active=None, limit=10, offset=0)
        out, out_total = repo.list_loans(member_id=None, active=True, limit=10, offset=0)
        back, _ = repo.list_loans(member_id=None, active=False, limit=10, offset=0)

        assert everything == loans[:2]
        assert total == 3
        assert mine == [loans[0], loans[2]]
        assert mine_total == 2
        assert out == loans[:2]
        assert out_total == 2
        assert back == [loans[2]]

    def test_repository_methods_can_be_called_inside_a_transaction(self, repo: LoanRepository) -> None:
        loan = LoanFactory.build()

        with repo.transaction():
            repo.add(loan)
            assert repo.count_active_for_book(loan.book_id) == 1


class TestInMemoryLoanRepository(LoanRepositoryContract):
    @pytest.fixture
    def repo(self) -> LoanRepository:
        return InMemoryLoanRepository()
