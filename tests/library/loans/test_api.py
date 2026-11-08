from datetime import UTC, date, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient

from fastapi_szumplate.library.loans.dependencies import get_today
from fastapi_szumplate.main import create_app
from tests.conftest import make_settings
from tests.library.factories import book_payload, isbn_for

PROBLEM = "application/problem+json"
MISSING_ID = "0192f5e0-5a3b-7c11-9d2e-3f6a1b2c4d5e"
TYPE = "urn:problem:fastapi-szumplate:"

pytestmark = pytest.mark.usefixtures("pinned_clock")  # today is 2026-01-06


def add_book(api: TestClient, number: int = 1, *, copies: int = 1) -> str:
    response = api.post("/v1/books", json=book_payload(isbn=isbn_for(number), copies=copies))
    assert response.status_code == 201
    return str(response.json()["id"])


def borrow(api: TestClient, book_id: str, member_id: str = "member-1") -> Any:
    return api.post("/v1/loans", json={"book_id": book_id, "member_id": member_id})


def test_lending_returns_201_a_location_and_the_dates(api: TestClient) -> None:
    book_id = add_book(api)

    response = borrow(api, book_id, "member-1")

    body = response.json()
    assert response.status_code == 201
    assert response.headers["Location"] == f"/v1/loans/{body['id']}"
    assert (body["book_id"], body["member_id"]) == (book_id, "member-1")
    assert (body["borrowed_on"], body["due_on"], body["returned_on"]) == (
        "2026-01-06",
        "2026-01-20",
        None,
    )


def test_lent_loan_can_be_fetched(api: TestClient) -> None:
    loan = borrow(api, add_book(api)).json()

    response = api.get(f"/v1/loans/{loan['id']}")

    assert response.status_code == 200
    assert response.json() == loan


def test_lending_an_unknown_book_is_a_404(api: TestClient) -> None:
    response = borrow(api, MISSING_ID)

    assert response.status_code == 404
    assert response.json()["type"] == f"{TYPE}book-not-found"
    assert response.headers["content-type"] == PROBLEM


def test_unknown_loan_is_a_404(api: TestClient) -> None:
    response = api.get(f"/v1/loans/{MISSING_ID}")

    assert response.status_code == 404
    assert response.json()["type"] == f"{TYPE}loan-not-found"


def test_a_book_with_no_free_copy_is_a_409(api: TestClient) -> None:
    book_id = add_book(api, copies=1)
    borrow(api, book_id, "member-1")

    response = borrow(api, book_id, "member-2")

    assert response.status_code == 409
    assert response.json()["type"] == f"{TYPE}no-free-copy"


def test_the_same_member_and_book_twice_is_a_409(api: TestClient) -> None:
    book_id = add_book(api, copies=2)
    borrow(api, book_id, "member-1")

    response = borrow(api, book_id, "member-1")

    assert response.status_code == 409
    assert response.json()["type"] == f"{TYPE}already-borrowed"


def test_a_fourth_active_loan_is_a_409(api: TestClient) -> None:
    for number in range(1, 4):
        assert borrow(api, add_book(api, number)).status_code == 201
    fourth = add_book(api, 4)

    response = borrow(api, fourth)

    assert response.status_code == 409
    assert response.json()["type"] == f"{TYPE}member-limit-reached"


def test_rule_order_is_already_borrowed_then_limit_then_stock(api: TestClient) -> None:
    held = [add_book(api, n) for n in range(1, 4)]
    for book_id in held:
        borrow(api, book_id, "member-1")
    scarce = add_book(api, 4, copies=1)
    borrow(api, scarce, "member-2")  # the only copy is out

    holds_it_already = borrow(api, held[0], "member-1")  # also at the limit and no copy is free
    at_the_limit = borrow(api, scarce, "member-1")  # at the limit and no copy is free

    assert holds_it_already.json()["type"] == f"{TYPE}already-borrowed"
    assert at_the_limit.json()["type"] == f"{TYPE}member-limit-reached"


def test_return_defaults_to_today_and_frees_the_copy(api: TestClient) -> None:
    book_id = add_book(api)
    loan = borrow(api, book_id, "member-1").json()

    response = api.post(f"/v1/loans/{loan['id']}/return")

    assert response.status_code == 200
    assert response.json()["returned_on"] == "2026-01-06"
    assert borrow(api, book_id, "member-2").status_code == 201


def test_return_accepts_a_date(api: TestClient) -> None:
    loan = borrow(api, add_book(api)).json()

    response = api.post(f"/v1/loans/{loan['id']}/return", json={"returned_on": "2026-01-10"})

    assert response.json()["returned_on"] == "2026-01-10"


def test_returning_twice_is_a_409(api: TestClient) -> None:
    loan = borrow(api, add_book(api)).json()
    api.post(f"/v1/loans/{loan['id']}/return")

    response = api.post(f"/v1/loans/{loan['id']}/return")

    assert response.status_code == 409
    assert response.json()["type"] == f"{TYPE}loan-already-returned"


def test_returning_before_the_borrow_date_is_a_409_not_a_422(api: TestClient) -> None:
    loan = borrow(api, add_book(api)).json()

    response = api.post(f"/v1/loans/{loan['id']}/return", json={"returned_on": "2026-01-05"})

    assert response.status_code == 409
    assert response.json()["type"] == f"{TYPE}returned-before-borrowed"


def test_returning_an_unknown_loan_is_a_404(api: TestClient) -> None:
    assert api.post(f"/v1/loans/{MISSING_ID}/return").status_code == 404


def test_list_filters_by_member_and_activity(api: TestClient) -> None:
    first = borrow(api, add_book(api, 1), "member-1").json()
    second = borrow(api, add_book(api, 2), "member-1").json()
    borrow(api, add_book(api, 3), "member-2")
    api.post(f"/v1/loans/{second['id']}/return")

    mine = api.get("/v1/loans", params={"member_id": "member-1", "active": "true"}).json()
    returned = api.get("/v1/loans", params={"active": "false"}).json()
    paged = api.get("/v1/loans", params={"limit": 1, "offset": 1}).json()

    assert [loan["id"] for loan in mine["items"]] == [first["id"]]
    assert mine["total"] == 1
    assert [loan["id"] for loan in returned["items"]] == [second["id"]]
    assert (paged["total"], len(paged["items"]), paged["limit"], paged["offset"]) == (3, 1, 1, 1)


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("post", "/v1/loans", {"book_id": "nope", "member_id": "m"}),
        ("post", "/v1/loans", {"book_id": MISSING_ID, "member_id": ""}),
        ("post", "/v1/loans", {"book_id": MISSING_ID, "member_id": "has space"}),
        ("post", "/v1/loans", {"book_id": MISSING_ID}),
        ("post", "/v1/loans", {"book_id": MISSING_ID, "member_id": "m", "extra": True}),
        ("get", "/v1/loans/not-a-uuid", None),
        ("get", "/v1/loans?limit=0", None),
        ("get", "/v1/loans?active=maybe", None),
        ("post", f"/v1/loans/{MISSING_ID}/return", {"returned_on": 0}),
        ("post", f"/v1/loans/{MISSING_ID}/return", {"returned_on": "06/01/2026"}),
        ("post", f"/v1/loans/{MISSING_ID}/return", {"returned_on": "2026-01-06T10:00:00"}),
        ("post", "/v1/loans/not-a-uuid/return", None),
    ],
    ids=[
        "book-id-not-uuid",
        "empty-member",
        "member-with-space",
        "missing-member",
        "extra-field",
        "get-bad-uuid",
        "limit-zero",
        "active-not-bool",
        "return-date-as-number",
        "return-date-wrong-format",
        "return-date-is-datetime",
        "return-bad-uuid",
    ],
)
def test_invalid_input_is_a_422_problem(
    api: TestClient, method: str, path: str, payload: dict[str, Any] | None
) -> None:
    response = api.request(method, path, json=payload)

    assert response.status_code == 422
    assert response.headers["content-type"] == PROBLEM
    assert response.json()["type"] == f"{TYPE}validation-error"


def return_loan(api: TestClient, loan: dict[str, Any], **kwargs: Any) -> Any:
    return api.post(f"/v1/loans/{loan['id']}/return", **kwargs)


def app_on(day: date, **settings: Any) -> TestClient:
    """A full app whose clock stands still on `day`, with the given settings."""
    app = create_app(make_settings(**settings))
    app.dependency_overrides[get_today] = lambda: lambda: day
    return TestClient(app)


@pytest.mark.parametrize("member_id", ["a" * 64, "a.b_c-d", "0", "Member-1", "UPPER.lower_09"])
def test_a_member_id_of_allowed_characters_and_length_is_accepted_as_written(api: TestClient, member_id: str) -> None:
    response = borrow(api, add_book(api), member_id)

    assert response.status_code == 201
    assert response.json()["member_id"] == member_id


@pytest.mark.parametrize(
    "member_id",
    ["a" * 65, "\u00e9", "m\n", "m m", "a/b", "m@x", "", None, 5, ["m"]],
    ids=["65-chars", "accented", "newline", "space", "slash", "at", "empty", "null", "int", "list"],
)
def test_a_member_id_outside_the_pattern_is_a_422_naming_the_field(api: TestClient, member_id: Any) -> None:
    response = api.post("/v1/loans", json={"book_id": add_book(api), "member_id": member_id})

    assert response.status_code == 422
    assert [i["loc"] for i in response.json()["errors"]] == [["body", "member_id"]]
    assert api.get("/v1/loans").json()["total"] == 0


@pytest.mark.parametrize(
    "content",
    [b"", b"null", b"[]", b'"x"', b'{"book_id": ', b"{}"],
    ids=["empty", "null", "array", "string", "truncated", "{}"],
)
def test_a_lending_body_that_is_not_a_loan_object_is_a_422(api: TestClient, content: bytes) -> None:
    response = api.post("/v1/loans", content=content, headers={"Content-Type": "application/json"})

    assert response.status_code == 422
    assert response.headers["content-type"] == PROBLEM


def test_a_book_id_of_another_type_is_a_422(api: TestClient) -> None:
    for book_id in (5, None, "", "0192f5e0", [MISSING_ID]):
        response = api.post("/v1/loans", json={"book_id": book_id, "member_id": "m"})

        assert response.status_code == 422, book_id


def test_a_lending_body_that_is_not_text_is_a_400_problem(api: TestClient) -> None:
    response = api.post("/v1/loans", content=b"\xff\xfe\x00", headers={"Content-Type": "application/json"})

    assert response.status_code == 400
    assert response.headers["content-type"] == PROBLEM


def test_an_unknown_book_is_a_404_even_for_a_member_who_is_at_the_limit(api: TestClient) -> None:
    for number in range(1, 4):
        borrow(api, add_book(api, number), "member-1")

    response = borrow(api, MISSING_ID, "member-1")

    assert response.status_code == 404
    assert response.json()["type"] == f"{TYPE}book-not-found"


def test_an_invalid_member_is_a_422_before_the_book_is_looked_up(api: TestClient) -> None:
    assert borrow(api, MISSING_ID, "no spaces").status_code == 422


def test_a_refused_lending_creates_no_loan(api: TestClient) -> None:
    scarce = add_book(api, 1, copies=1)
    borrow(api, scarce, "member-1")

    refusals = [
        borrow(api, scarce, "member-1"),  # already borrowed
        borrow(api, scarce, "member-2"),  # no free copy
        borrow(api, MISSING_ID, "member-2"),  # unknown book
    ]

    assert [r.status_code for r in refusals] == [409, 409, 404]
    assert api.get("/v1/loans").json()["total"] == 1


def test_every_copy_can_be_lent_and_the_next_request_is_refused(api: TestClient) -> None:
    book_id = add_book(api, 1, copies=3)

    statuses = [borrow(api, book_id, f"member-{n}").status_code for n in range(1, 5)]

    assert statuses == [201, 201, 201, 409]


def test_a_member_may_hold_exactly_the_limit_and_one_more_is_refused(api: TestClient) -> None:
    books = [add_book(api, n) for n in range(1, 5)]

    statuses = [borrow(api, book_id, "member-1").status_code for book_id in books]

    assert statuses == [201, 201, 201, 409]


def test_the_limit_is_per_member(api: TestClient) -> None:
    for number in range(1, 4):
        borrow(api, add_book(api, number, copies=2), "member-1")
    shared = add_book(api, 4, copies=2)

    assert borrow(api, shared, "member-1").status_code == 409
    assert borrow(api, shared, "member-2").status_code == 201


def test_member_ids_are_case_sensitive(api: TestClient) -> None:
    book_id = add_book(api, 1, copies=2)

    assert borrow(api, book_id, "Member").status_code == 201
    assert borrow(api, book_id, "member").status_code == 201


def test_returned_loans_do_not_count_toward_the_limit(api: TestClient) -> None:
    loans = [borrow(api, add_book(api, n), "member-1").json() for n in range(1, 4)]
    return_loan(api, loans[0])
    return_loan(api, loans[1])

    first = borrow(api, add_book(api, 4), "member-1")
    second = borrow(api, add_book(api, 5), "member-1")
    third = borrow(api, add_book(api, 6), "member-1")

    assert [r.status_code for r in (first, second, third)] == [201, 201, 409]


def test_a_member_can_borrow_the_same_book_again_after_returning_it(api: TestClient) -> None:
    book_id = add_book(api)
    first = borrow(api, book_id).json()
    return_loan(api, first)

    again = borrow(api, book_id)

    assert again.status_code == 201
    assert again.json()["id"] != first["id"]


def test_changing_a_book_does_not_free_or_take_a_copy(api: TestClient) -> None:
    book_id = add_book(api, copies=1)
    borrow(api, book_id, "member-1")

    api.put(f"/v1/books/{book_id}", json={"title": "Renamed", "author": "Other"})

    assert borrow(api, book_id, "member-2").status_code == 409
    assert api.get(f"/v1/books/{book_id}").json()["copies"] == 1


@pytest.mark.parametrize(
    "body",
    [{}, {"returned_on": None}],
    ids=["empty-object", "null-date"],
)
def test_a_return_without_a_date_is_today(api: TestClient, body: dict[str, Any]) -> None:
    loan = borrow(api, add_book(api)).json()

    response = return_loan(api, loan, json=body)

    assert response.status_code == 200
    assert response.json()["returned_on"] == "2026-01-06"


@pytest.mark.parametrize("content", [b"", b"null"], ids=["no-body", "json-null"])
def test_a_return_with_an_empty_or_null_json_body_is_today(api: TestClient, content: bytes) -> None:
    loan = borrow(api, add_book(api)).json()

    response = return_loan(api, loan, content=content, headers={"Content-Type": "application/json"})

    assert response.status_code == 200
    assert response.json()["returned_on"] == "2026-01-06"


@pytest.mark.parametrize(
    "day",
    ["2026-01-06", "2026-01-20", "2026-01-21"],
    ids=["same-day", "due", "late"],
)
def test_a_return_on_or_after_the_borrow_day_is_accepted(api: TestClient, day: str) -> None:
    loan = borrow(api, add_book(api)).json()

    response = return_loan(api, loan, json={"returned_on": day})

    assert response.status_code == 200
    assert response.json()["returned_on"] == day
    assert api.get(f"/v1/loans/{loan['id']}").json()["returned_on"] == day


def test_a_return_the_day_before_the_borrow_day_is_refused_and_the_loan_stays_out(
    api: TestClient,
) -> None:
    book_id = add_book(api, copies=1)
    loan = borrow(api, book_id, "member-1").json()

    refused = return_loan(api, loan, json={"returned_on": "2026-01-05"})

    assert refused.status_code == 409
    assert refused.json()["type"] == f"{TYPE}returned-before-borrowed"
    assert api.get(f"/v1/loans/{loan['id']}").json()["returned_on"] is None
    assert borrow(api, book_id, "member-2").status_code == 409  # the copy is still out
    assert return_loan(api, loan, json={"returned_on": "2026-01-06"}).status_code == 200


def test_a_second_return_dated_before_the_borrow_day_is_already_returned_not_returned_before(
    api: TestClient,
) -> None:
    loan = borrow(api, add_book(api)).json()
    assert return_loan(api, loan, json={"returned_on": "2026-01-08"}).status_code == 200

    refused = return_loan(api, loan, json={"returned_on": "2026-01-05"})

    assert refused.status_code == 409
    assert refused.json()["type"] == f"{TYPE}loan-already-returned"


def test_a_second_return_keeps_the_first_date(api: TestClient) -> None:
    loan = borrow(api, add_book(api)).json()
    return_loan(api, loan, json={"returned_on": "2026-01-08"})

    second = return_loan(api, loan, json={"returned_on": "2026-01-09"})

    assert second.status_code == 409
    assert api.get(f"/v1/loans/{loan['id']}").json()["returned_on"] == "2026-01-08"


@pytest.mark.parametrize(
    "returned_on",
    [
        "2026-02-30",
        "2026-13-01",
        "2026-1-6",
        "20260106",
        " 2026-01-06",
        "2026-01-06 ",
        "2026-01-06\n",
        "0000-01-01",
        "2026-01-06T00:00:00Z",
        "",
        "today",
        20260106,
        1.5,
        True,
        [],
    ],
    ids=lambda v: repr(v)[:20],
)
def test_a_return_date_that_is_not_an_iso_date_is_a_422_and_the_loan_stays_out(
    api: TestClient, returned_on: Any
) -> None:
    loan = borrow(api, add_book(api)).json()

    response = return_loan(api, loan, json={"returned_on": returned_on})

    assert response.status_code == 422
    assert response.json()["errors"][0]["loc"] == ["body", "returned_on"]
    assert api.get(f"/v1/loans/{loan['id']}").json()["returned_on"] is None


def test_an_unknown_field_in_the_return_body_is_a_422(api: TestClient) -> None:
    loan = borrow(api, add_book(api)).json()

    response = return_loan(api, loan, json={"returned_on": "2026-01-08", "member_id": "x"})

    assert response.status_code == 422
    assert api.get(f"/v1/loans/{loan['id']}").json()["returned_on"] is None


def test_a_bad_return_body_is_a_422_before_the_loan_is_looked_up(api: TestClient) -> None:
    response = api.post(f"/v1/loans/{MISSING_ID}/return", json={"returned_on": "nope"})

    assert response.status_code == 422


def test_a_return_body_that_is_not_text_is_a_400_problem(api: TestClient) -> None:
    loan = borrow(api, add_book(api)).json()

    response = return_loan(api, loan, content=b"\xff\xfe\x00", headers={"Content-Type": "application/json"})

    assert response.status_code == 400
    assert response.headers["content-type"] == PROBLEM


@pytest.mark.parametrize(
    ("today", "due"),
    [
        (date(2026, 1, 6), "2026-01-20"),
        (date(2026, 12, 25), "2027-01-08"),
        (date(2028, 2, 15), "2028-02-29"),
        (date(2028, 2, 16), "2028-03-01"),
        (date(2027, 2, 15), "2027-03-01"),
    ],
    ids=["same-month", "new-year", "leap-day", "after-leap-day", "no-leap-day"],
)
def test_the_due_date_follows_the_calendar(today: date, due: str) -> None:
    client = app_on(today)
    book_id = client.post("/v1/books", json=book_payload()).json()["id"]

    loan = borrow(client, book_id).json()

    assert (loan["borrowed_on"], loan["due_on"]) == (today.isoformat(), due)


def test_the_configured_loan_days_and_member_limit_apply() -> None:
    client = app_on(date(2026, 1, 6), loan_days=7, loans_max_active_per_member=1)
    first = client.post("/v1/books", json=book_payload(isbn=isbn_for(1))).json()["id"]
    second = client.post("/v1/books", json=book_payload(isbn=isbn_for(2))).json()["id"]

    lent = borrow(client, first)
    refused = borrow(client, second)

    assert lent.json()["due_on"] == "2026-01-13"
    assert refused.status_code == 409
    assert refused.json()["type"] == f"{TYPE}member-limit-reached"


def test_the_clock_is_read_for_every_request_not_once() -> None:
    days = iter([date(2026, 1, 6), date(2026, 1, 9)])
    app = create_app(make_settings())
    app.dependency_overrides[get_today] = lambda: lambda: next(days)
    client = TestClient(app)
    book_id = client.post("/v1/books", json=book_payload()).json()["id"]

    loan = borrow(client, book_id).json()
    returned = return_loan(client, loan)

    assert loan["borrowed_on"] == "2026-01-06"
    assert returned.json()["returned_on"] == "2026-01-09"


def test_the_real_clock_lends_from_today() -> None:
    client = TestClient(create_app(make_settings()))
    book_id = client.post("/v1/books", json=book_payload()).json()["id"]

    loan = borrow(client, book_id).json()

    borrowed = date.fromisoformat(loan["borrowed_on"])
    assert abs((borrowed - datetime.now(UTC).date()).days) <= 1  # tolerates a UTC midnight crossing
    assert (date.fromisoformat(loan["due_on"]) - borrowed).days == 14


def test_listing_filters_by_the_exact_member_not_a_prefix(api: TestClient) -> None:
    borrow(api, add_book(api, 1), "member-1")
    borrow(api, add_book(api, 2), "member-10")

    body = api.get("/v1/loans", params={"member_id": "member-1"}).json()

    assert [loan["member_id"] for loan in body["items"]] == ["member-1"]
    assert body["total"] == 1


def test_listing_returns_loans_oldest_first_with_a_total_that_ignores_the_page(
    api: TestClient,
) -> None:
    created = [borrow(api, add_book(api, n), f"member-{n}").json()["id"] for n in range(1, 6)]

    walked: list[str] = []
    for offset in (0, 2, 4):
        page = api.get("/v1/loans", params={"limit": 2, "offset": offset}).json()
        assert page["total"] == 5
        walked += [loan["id"] for loan in page["items"]]

    assert walked == created


def test_listing_filters_combine_and_an_empty_match_is_an_empty_page(api: TestClient) -> None:
    kept = borrow(api, add_book(api, 1), "member-1").json()
    gone = borrow(api, add_book(api, 2), "member-1").json()
    return_loan(api, gone)
    borrow(api, add_book(api, 3), "member-2")

    active = api.get("/v1/loans", params={"member_id": "member-1", "active": "true"}).json()
    done = api.get("/v1/loans", params={"member_id": "member-1", "active": "false"}).json()
    nobody = api.get("/v1/loans", params={"member_id": "member-9"}).json()
    other_done = api.get("/v1/loans", params={"member_id": "member-2", "active": "false"}).json()

    assert [loan["id"] for loan in active["items"]] == [kept["id"]]
    assert [loan["id"] for loan in done["items"]] == [gone["id"]]
    assert nobody == {"items": [], "total": 0, "limit": 20, "offset": 0}
    assert other_done["total"] == 0


def test_a_returned_loan_moves_from_the_active_list_to_the_returned_list(api: TestClient) -> None:
    loan = borrow(api, add_book(api)).json()
    before = api.get("/v1/loans", params={"active": "true"}).json()["total"]

    return_loan(api, loan)

    assert before == 1
    assert api.get("/v1/loans", params={"active": "true"}).json()["total"] == 0
    assert api.get("/v1/loans", params={"active": "false"}).json()["total"] == 1


@pytest.mark.parametrize(
    "query",
    [
        "limit=0",
        "limit=101",
        "limit=-1",
        "limit=",
        "offset=-1",
        "offset=x",
        "member_id=",
        "member_id=" + "m" * 65,
        "active=",
        "active=maybe",
        "active=2",
    ],
)
def test_malformed_list_parameters_are_a_422_naming_the_parameter(api: TestClient, query: str) -> None:
    response = api.get(f"/v1/loans?{query}")

    assert response.status_code == 422
    assert response.headers["content-type"] == PROBLEM
    assert response.json()["errors"][0]["loc"] == ["query", query.split("=")[0]]


@pytest.mark.parametrize("query", ["limit=1", "limit=100", "member_id=" + "m" * 64, "active=false"])
def test_list_parameters_on_the_edge_are_accepted(api: TestClient, query: str) -> None:
    assert api.get(f"/v1/loans?{query}").status_code == 200


def test_an_offset_past_the_end_is_an_empty_page_with_the_real_total(api: TestClient) -> None:
    borrow(api, add_book(api))

    body = api.get("/v1/loans", params={"offset": 5}).json()

    assert (body["items"], body["total"], body["offset"]) == ([], 1, 5)


def test_a_loan_from_the_list_equals_the_loan_fetched_by_id(api: TestClient) -> None:
    loan = borrow(api, add_book(api)).json()
    return_loan(api, loan, json={"returned_on": "2026-01-07"})

    listed = api.get("/v1/loans").json()["items"][0]

    assert listed == api.get(f"/v1/loans/{loan['id']}").json()
    assert listed["returned_on"] == "2026-01-07"


def test_loan_responses_are_application_json(api: TestClient) -> None:
    created = borrow(api, add_book(api))

    for response in (
        created,
        api.get(created.headers["Location"]),
        api.get("/v1/loans"),
        return_loan(api, created.json()),
    ):
        assert response.headers["content-type"] == "application/json"


def test_a_loan_filter_given_twice_is_a_422(api: TestClient) -> None:
    response = api.get("/v1/loans?member_id=a&member_id=b")

    assert response.status_code == 422
    assert [issue["loc"] for issue in response.json()["errors"]] == [["query", "member_id"]]
