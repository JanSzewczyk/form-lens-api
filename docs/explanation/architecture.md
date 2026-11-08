# Architecture

## Domain first, layers inside

Top-level packages are business areas; the layers (router, schemas, service, repository) sit
inside each. A change to one area edits one folder. `health` is the one area the core ships.

<!-- begin:example -->
The example adds `library/books` and `library/loans`: a change to "loans" edits one folder.
<!-- end:example -->

## Module shapes, and one rule for choosing

- **Default shape**: router, schemas, models, service, repository. The service is a few lines and
  holds no rule that belongs to a domain object. Every new module starts here.
- **Hexagonal shape**: `domain/` holds the rules as methods of the domain objects and imports
  nothing but the standard library; `domain/ports.py` declares what the module needs;
  `service_layer/` gathers facts and calls the domain; `adapters/` implement the ports;
  `entrypoints/` is the HTTP side.

Structure is added to one module at a time, when it hurts: the same rule copied in several places,
a rule test that needs a database, business terms missing from the code. Do not convert a module
to match another.

<!-- begin:example -->
`books` has the default shape (its only rule is "an ISBN is unique"); `loans` has the hexagonal
one, with `Loan.lend` and `Loan.give_back` in `domain/`. Do not convert `books` to match `loans`.
<!-- end:example -->

## Import direction

Routers depend on services, services on the domain and its ports, adapters on the domain. The
domain imports no web framework, no ORM, no adapter. Only `dependencies.py` and the code that
wires the app (`main.py`) import adapters. Modules refer to one another by id and never import
each other's models. `make imports` enforces the contracts in `pyproject.toml`.

The core has layers of its own: `__main__` (the only module that imports uvicorn), then the
factory `main.py`, then the features (`health`, `middleware`, `openapi`, `logging_config`,
`pagination`), then the foundations (`problems`, `config`, `query`, `types`). A layer imports only
the layers below it. A new core module joins the contract in the layer it belongs to.

<!-- begin:example -->
Only `dependencies.py`, `library/__init__.py` and `main.py` import adapters. `loans` asks `books`
for one number (the capacity) through `loans/adapters/books_catalog.py`.

## The core never knows the example

`main.py` calls `include_library(app)`; nothing else outside `library/` mentions it. That is what
makes the example removable as a unit.
<!-- end:example -->

## Wiring

`create_app(settings)` builds the app. Adapters are built once and stored on `app.state`;
dependencies read them from the request, so tests replace them with `app.dependency_overrides` and
the app never has module-level state.

<!-- begin:example -->
The example's repositories are built in `include_library`.
<!-- end:example -->

## Logging is configured twice, on purpose

`configure_logging(settings)` runs in `__main__.main()` and again inside every `create_app()`. It
is idempotent: it removes only the handler it installed before it installs a new one, so the
second call replaces the first instead of doubling every line. `main()` configures logging before
it hands control to uvicorn, which then starts with `log_config=None`. `create_app()` configures it
again because the app can be built without `main()`: by `uvicorn <package>.main:create_app
--factory`, and by every test.

## Why handlers are sync `def`

Routes run in Starlette's threadpool. The service does no async I/O, and plain `def` makes
parallel tests meaningful: concurrent requests really run at the same time. Switch a route to
`async def` only when it awaits something, and then give each awaited call a timeout.

## Strict input without surprises

Pydantic's lax mode reads `0` as `1970-01-01` and `"3"` as `3`, which the spec does not allow.
Dates use `IsoDate` and integers use `WholeNumber` (a whole number, written `3` or `3.0`, never a
string or a bool). Whole-model strict mode was rejected because it also refuses valid date and UUID
strings.

## Concurrency

A rule that reads before it writes is guarded by one atomic step, and each guard has a parallel
test that fails without it. See [add-a-module](../how-to/add-a-module.md).
<!-- begin:example -->
[swap-in-a-database](../how-to/swap-in-a-database.md) shows the guards in SQL.
<!-- end:example -->
