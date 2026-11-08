# Add a module

Create a package next to `health/` (or inside your own domain package) and start with the default
shape.

<!-- begin:example -->
The example's `library/books/` is the model to copy.
<!-- end:example -->

## 1. The default shape

```text
orders/
  router.py        parse, call one service method, shape the response
  schemas.py       Pydantic request and response models (OrderCreate, OrderUpdate, OrderResponse)
  models.py        the entity: a frozen dataclass, or a database model
  service.py       use cases; knows nothing of HTTP
  repository.py    a Protocol and an adapter
  dependencies.py  builds the service from objects the app owns
  exceptions.py    domain errors, no HTTP
  errors.py        maps each exception to a ProblemType
```

## 2. Rules to follow

- A route only parses, calls **one** service method and leaves errors to the registered handler.
- Give every route an explicit `operation_id` (`verb_resource`), a `response_model` or return
  annotation, and `responses` listing every status it can return, with `problem_response(...)`.
  Routes with input document `422`; routes with a JSON body also document `400`
  (`malformed_body_response()`).
- Describe every field: `Field(description=..., examples=[...])`. An example never depends on
  stored data or today's date.
- Route docstrings are a summary plus prose for API consumers. No `Args:` or `Returns:` sections;
  they would end up in the spec (a test fails if they do).
- Each domain error gets its own `ProblemType("slug", "Stable title", status)`; the
  `type` becomes `urn:problem:<service>:<slug>`. Register them with
  `register_domain_errors(app, ERRORS)`.
- A request that the *stored state* forbids is a 409. A request that is wrong on its own is a 422.

## 3. Wire it

Build adapters once, store them on `app.state`, and read them in `dependencies.py` through the
request. Do not build adapters per request and do not use module globals.

```python
app.state.order_repository = InMemoryOrderRepository()
app.include_router(orders_router)
register_domain_errors(app, ORDER_ERRORS)
add_tags(app, {"name": "orders", "description": "..."})
```

Put the version prefix in the router (`APIRouter(prefix="/v1/orders")`) so the route template in
the access log is the full path.

## 4. State-dependent rules

If a rule reads before it writes (a stock, a per-member limit, a unique value), the check and the
write must be one atomic step, and a test must prove it:

1. Give the repository one guard (a lock, a conditional `UPDATE`, a unique index).
2. Write a parallel test: a `threading.Barrier`, one `TestClient` per thread, assert the sorted
   status codes and the final state. Widen the race window with a test-only repository subclass
   that sleeps after a read.
3. Remove the guard once and watch the test fail. Run the mutant from a copy of the repository and
   print `fastapi_szumplate.__file__` first; an editable install otherwise imports the original
   and the test stays green.

<!-- begin:example -->
The example does this in `tests/library/loans/test_concurrency.py`.
<!-- end:example -->

## 5. Move a module to the hexagonal shape

Only when a concrete pain shows: the same rule copied in several places, a rule test that needs a
database, or business terms missing from the code. Then add `domain/` (rules, standard library
only), `domain/ports.py`, `service_layer/`, `adapters/` and `entrypoints/`, and an import-linter
contract that points the layers toward the domain.

<!-- begin:example -->
`library/loans/` is the model, and its contract is "Loans layers point toward the domain".
<!-- end:example -->

## 6. Finish

```bash
make openapi    # regenerate and commit openapi.json
make check
```
