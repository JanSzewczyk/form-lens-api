# Swap the in-memory repositories for a database

The example keeps data in memory behind two ports: `BookRepository` (`library/books/repository.py`)
and `LoanRepository` (`library/loans/domain/ports.py`). A database adapter implements the same
Protocol and must pass the same contract suite. No service, route or schema changes.

Until you have done this, run one worker and one replica: the repositories and the `RLock` that
makes each rule atomic live in one process, so a second worker would have its own data and its
own locks.

## 1. Write the adapter

Create `library/books/sql_repository.py` and `library/loans/adapters/sql_repository.py`. They may
import SQLAlchemy; nothing else may (the import contracts keep the domain clean). Map the
database rows to the existing dataclasses (`Book`, `Loan`) inside the adapter.

## 2. Prove it with the contract suite

`tests/library/contract/test_repositories.py` holds the behaviour every adapter must have. Add a
subclass that provides the `repo` fixture:

```python
class TestSqlBookRepository(BookRepositoryContract):
    @pytest.fixture
    def repo(self, engine: Engine) -> BookRepository:
        return SqlBookRepository(sessionmaker(engine))
```

Run it against the production engine (PostgreSQL through testcontainers), not a stand-in: a SQLite
substitute accepts SQL the real engine rejects.

## 3. Replace each in-memory guard

The in-memory adapters make a check and its write atomic with a lock. In SQL the database does it:

| Rule | In-memory guard | SQL guard |
| --- | --- | --- |
| ISBN is unique | check and insert under one lock | `UNIQUE` index on `isbn`; catch `IntegrityError`, `rollback()`, raise `IsbnAlreadyExists` only for that constraint, re-raise the rest |
| A copy is free | `transaction()` around count and add | In `transaction()`, `SELECT ... FROM books WHERE id = :id FOR UPDATE`, then count and insert |
| Member limit | the same `transaction()` | Lock a per-member row (or `pg_advisory_xact_lock(hashtext(member_id))`), count, insert. A count cannot be one `UPDATE` |
| Same member and book twice | the same `transaction()` | Partial unique index on `(member_id, book_id) WHERE returned_on IS NULL`, mapped like the ISBN |
| Loan returned once | `transaction()` plus the domain check | `UPDATE loans SET returned_on = :d WHERE id = :id AND returned_on IS NULL`; zero rows means already returned |
| Return not before borrow | domain check | none; it needs no lock |

`transaction()` becomes a context manager that opens a database transaction and commits or rolls
back. Keep the domain checks (`Loan.lend`, `Loan.give_back`): they give the readable rule and the
right error; the database makes it hold under concurrent requests.

## 4. Prove the guards again

Run `tests/library/*/test_concurrency.py` against the adapter. They use a repository subclass that
sleeps after reads; with a database, use the real latency or force the interleaving with a barrier
between the read and the write. Remove each guard once and confirm the matching test goes red.

## 5. Wire it

Build the adapter once in `include_library` (`library/__init__.py`) and store it on `app.state` in
place of the in-memory one. Add the database check to readiness:

```python
register_readiness_check(app, "database", lambda: engine.connect().close())
```

Add the driver with `uv add`, commit `uv.lock`, and run `make check`.
