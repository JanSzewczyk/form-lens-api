import re
import sys
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from hypothesis import example, given, settings
from hypothesis import strategies as st
from pydantic import TypeAdapter, ValidationError

from fastapi_szumplate.library.books.schemas import NON_BLANK, Title
from fastapi_szumplate.main import create_app
from tests.conftest import make_settings
from tests.library.factories import book_payload, isbn_for

PROBLEM = "application/problem+json"
MISSING_ID = "0192f5e0-5a3b-7c11-9d2e-3f6a1b2c4d5e"


def create_book(client: TestClient, **overrides: Any) -> dict[str, Any]:
    response = client.post("/v1/books", json=book_payload(**overrides))
    assert response.status_code == 201
    return dict(response.json())


def test_create_returns_201_with_the_book_and_a_location(api: TestClient) -> None:
    response = api.post(
        "/v1/books",
        json={"isbn": isbn_for(1), "title": "Clean Code", "author": "R. Martin", "copies": 3},
    )

    body = response.json()
    assert response.status_code == 201
    assert response.headers["Location"] == f"/v1/books/{body['id']}"
    assert {k: body[k] for k in ("isbn", "title", "author", "copies")} == {
        "isbn": isbn_for(1),
        "title": "Clean Code",
        "author": "R. Martin",
        "copies": 3,
    }


def test_created_book_can_be_fetched(api: TestClient) -> None:
    book = create_book(api, title="Refactoring")

    response = api.get(f"/v1/books/{book['id']}")

    assert response.status_code == 200
    assert response.json() == book


def test_duplicate_isbn_is_a_409_with_its_own_type(api: TestClient) -> None:
    create_book(api, isbn=isbn_for(9))

    response = api.post("/v1/books", json=book_payload(isbn=isbn_for(9)))

    assert response.status_code == 409
    assert response.headers["content-type"] == PROBLEM
    assert response.json()["type"] == "urn:problem:fastapi-szumplate:isbn-already-exists"


def test_unknown_book_is_a_404_problem(api: TestClient) -> None:
    response = api.get(f"/v1/books/{MISSING_ID}")

    assert response.status_code == 404
    assert response.json()["type"] == "urn:problem:fastapi-szumplate:book-not-found"
    assert response.headers["content-type"] == PROBLEM


def test_update_changes_title_and_author(api: TestClient) -> None:
    book = create_book(api, copies=2)

    response = api.put(f"/v1/books/{book['id']}", json={"title": "New", "author": "Other"})

    assert response.status_code == 200
    assert response.json() == {**book, "title": "New", "author": "Other"}
    assert api.get(f"/v1/books/{book['id']}").json()["title"] == "New"


def test_update_of_an_unknown_book_is_a_404(api: TestClient) -> None:
    response = api.put(f"/v1/books/{MISSING_ID}", json={"title": "T", "author": "A"})

    assert response.status_code == 404


def test_list_is_paged_and_reports_the_total(api: TestClient) -> None:
    for number in range(1, 6):
        create_book(api, isbn=isbn_for(number))

    response = api.get("/v1/books", params={"limit": 2, "offset": 2})

    body = response.json()
    assert response.status_code == 200
    assert (body["total"], body["limit"], body["offset"]) == (5, 2, 2)
    assert [b["isbn"] for b in body["items"]] == [isbn_for(3), isbn_for(4)]


def test_list_uses_the_configured_page_size_by_default(api: TestClient) -> None:
    body = api.get("/v1/books").json()

    assert body == {"items": [], "total": 0, "limit": 20, "offset": 0}


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("post", "/v1/books", {"isbn": "123", "title": "T", "author": "A", "copies": 1}),
        ("post", "/v1/books", {"isbn": isbn_for(1), "title": "", "author": "A", "copies": 1}),
        ("post", "/v1/books", {"isbn": isbn_for(1), "title": "T", "author": "A", "copies": 0}),
        ("post", "/v1/books", {"isbn": isbn_for(1), "title": "T", "author": "A", "copies": "3"}),
        ("post", "/v1/books", {"isbn": isbn_for(1), "title": "T", "author": "A", "copies": 1.5}),
        ("post", "/v1/books", {"isbn": isbn_for(1), "title": "T", "author": "A", "copies": True}),
        ("post", "/v1/books", {"isbn": isbn_for(1), "title": "T", "author": "A"}),
        (
            "post",
            "/v1/books",
            {"isbn": isbn_for(1), "title": "T", "author": "A", "copies": 1, "extra": 1},
        ),
        ("put", f"/v1/books/{MISSING_ID}", {"title": "T"}),
        ("put", "/v1/books/not-a-uuid", {"title": "T", "author": "A"}),
        ("get", "/v1/books/not-a-uuid", None),
        ("get", "/v1/books?limit=0", None),
        ("get", "/v1/books?limit=101", None),
        ("get", "/v1/books?offset=-1", None),
        ("get", "/v1/books?limit=ten", None),
    ],
    ids=[
        "isbn-pattern",
        "empty-title",
        "zero-copies",
        "copies-as-string",
        "copies-with-fraction",
        "copies-as-bool",
        "missing-copies",
        "extra-field",
        "update-missing-author",
        "update-bad-uuid",
        "get-bad-uuid",
        "limit-zero",
        "limit-too-big",
        "negative-offset",
        "limit-not-int",
    ],
)
def test_invalid_input_is_a_422_problem(
    api: TestClient, method: str, path: str, payload: dict[str, Any] | None
) -> None:
    response = api.request(method, path, json=payload)

    assert response.status_code == 422
    assert response.headers["content-type"] == PROBLEM
    assert response.json()["type"] == "urn:problem:fastapi-szumplate:validation-error"


def test_wrong_method_is_a_405_with_allow(api: TestClient) -> None:
    response = api.delete("/v1/books")

    assert response.status_code == 405
    assert response.headers["Allow"] == "GET, POST"


def test_unversioned_path_is_a_404(api: TestClient) -> None:
    assert api.get("/books").status_code == 404


def test_access_log_uses_the_full_route_template(api: TestClient, capsys: pytest.CaptureFixture[str]) -> None:
    api.get(f"/v1/books/{MISSING_ID}")

    assert '"route": "/v1/books/{book_id}"' in capsys.readouterr().out


def test_a_whole_number_written_with_a_fraction_is_an_integer(api: TestClient) -> None:
    """JSON Schema says 3.0 is an integer, so the API accepts what its own spec allows."""
    response = api.post("/v1/books", json=book_payload(copies=3.0))

    assert response.status_code == 201
    assert response.json()["copies"] == 3


def test_a_body_that_is_not_text_is_a_400_problem(api: TestClient) -> None:
    response = api.post("/v1/books", content=b"\xff\xfe\x00", headers={"Content-Type": "application/json"})

    assert response.status_code == 400
    assert response.headers["content-type"] == PROBLEM
    assert response.json()["title"] == "Bad Request"


ARABIC_INDIC_ISBN = "\u0669\u0667\u0668\u0660\u0661\u0663\u0662\u0663\u0665\u0660\u0668\u0668\u0664"


@pytest.mark.parametrize(
    "overrides",
    [
        {"copies": 1},
        {"copies": 1000},
        {"title": "T"},
        {"title": "t" * 200},
        {"author": "a" * 200},
        {"title": "\u00e9" * 200},
        {"title": "\U0001f4da" * 200},
        {"isbn": "0" * 13},
    ],
    ids=[
        "copies-min",
        "copies-max",
        "title-one-char",
        "title-200",
        "author-200",
        "title-200-accented",
        "title-200-emoji",
        "isbn-all-zeros",
    ],
)
def test_values_on_the_edge_of_the_limits_are_accepted(api: TestClient, overrides: dict[str, Any]) -> None:
    payload = book_payload(**overrides)

    response = api.post("/v1/books", json=payload)

    assert response.status_code == 201
    assert {k: response.json()[k] for k in payload} == payload


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("isbn", "9" * 12),
        ("isbn", "9" * 14),
        ("isbn", ""),
        ("isbn", "978-0132350884"),
        ("isbn", "97801323508X4"),
        ("isbn", " 9780132350884"),
        ("isbn", "9780132350884 "),
        ("isbn", "9780132350884\n"),
        ("isbn", 9780132350884),
        ("isbn", None),
        ("title", "t" * 201),
        ("title", "\U0001f4da" * 201),
        ("title", None),
        ("title", 5),
        ("title", " "),
        ("title", " \t\n\u00a0"),
        ("author", "a" * 201),
        ("author", ""),
        ("author", "   "),
        ("author", None),
        ("copies", 1001),
        ("copies", 0),
        ("copies", -1),
        ("copies", 1000.5),
        ("copies", None),
        ("copies", [3]),
        ("copies", "3"),
    ],
    ids=lambda v: repr(v)[:18],
)
def test_a_value_outside_the_documented_limits_is_a_422_naming_the_field(
    api: TestClient, field: str, value: Any
) -> None:
    response = api.post("/v1/books", json=book_payload(**{field: value}))

    assert response.status_code == 422
    assert response.headers["content-type"] == PROBLEM
    assert [issue["loc"][:2] for issue in response.json()["errors"]] == [["body", field]]
    assert api.get("/v1/books").json()["total"] == 0


@pytest.mark.parametrize(
    "isbn",
    [
        ARABIC_INDIC_ISBN,
        "\uff19\uff17\uff18\uff10\uff11\uff13\uff12\uff13\uff15\uff10\uff18\uff18\uff14",
    ],
    ids=["arabic-indic-digits", "fullwidth-digits"],
)
def test_defect_2_an_isbn_of_non_ascii_digits_is_a_422(api: TestClient, isbn: str) -> None:
    """Defect 2: the spec pattern `^\\d{13}$` means ASCII digits in JSON Schema (ECMA-262)."""
    response = api.post("/v1/books", json=book_payload(isbn=isbn))

    assert response.status_code == 422


@given(isbn=st.text(alphabet=st.characters(categories=["Nd"]), min_size=13, max_size=13))
@example(isbn=ARABIC_INDIC_ISBN)
@example(isbn="9780132350884")
@settings(max_examples=60, deadline=None)
def test_defect_2_only_ascii_digits_make_an_isbn(isbn: str) -> None:
    """Defect 2, as a property: accepted exactly when the string is thirteen ASCII digits."""
    client = TestClient(create_app(make_settings()))

    response = client.post("/v1/books", json=book_payload(isbn=isbn))

    expected = 201 if re.fullmatch(r"[0-9]{13}", isbn) else 422
    assert response.status_code == expected


@given(isbn=st.text(alphabet="0123456789-X \n", max_size=15))
@settings(max_examples=60, deadline=None)
def test_an_ascii_string_is_stored_only_when_it_is_thirteen_digits(isbn: str) -> None:
    client = TestClient(create_app(make_settings()))

    response = client.post("/v1/books", json=book_payload(isbn=isbn))

    if re.fullmatch(r"[0-9]{13}", isbn):
        assert response.status_code == 201
    else:
        assert response.status_code == 422
        assert client.get("/v1/books").json()["total"] == 0


@pytest.mark.parametrize(
    ("content", "error_type"),
    [
        (b"", "missing"),
        (b"null", "model_attributes_type"),
        (b"[]", "model_attributes_type"),
        (b'"text"', "model_attributes_type"),
        (b"5", "model_attributes_type"),
        (b"true", "model_attributes_type"),
        (b'{"isbn": ', "json_invalid"),
        (b"{'isbn': '1'}", "json_invalid"),
        (b"{}", "missing"),
    ],
    ids=["empty", "null", "array", "string", "number", "bool", "truncated", "single-quotes", "{}"],
)
def test_a_body_that_is_not_a_book_object_is_a_422(api: TestClient, content: bytes, error_type: str) -> None:
    response = api.post("/v1/books", content=content, headers={"Content-Type": "application/json"})

    assert response.status_code == 422
    assert response.headers["content-type"] == PROBLEM
    assert response.json()["errors"][0]["type"] == error_type


def test_defect_3_valid_json_with_an_absurdly_long_integer_is_a_422_not_a_400(
    api: TestClient,
) -> None:
    """Defect 3 (stricter reading): the 400 is documented for bytes that are not text."""
    body = b'{"isbn": "9780132350884", "title": "T", "author": "A", "copies": ' + b"9" * 5000 + b"}"

    response = api.post("/v1/books", content=body, headers={"Content-Type": "application/json"})

    assert response.status_code == 422


def test_the_location_header_points_at_the_new_book(api: TestClient) -> None:
    created = api.post("/v1/books", json=book_payload())

    fetched = api.get(created.headers["Location"])

    assert fetched.status_code == 200
    assert fetched.json() == created.json()


def test_a_created_book_has_a_uuid_and_two_books_never_share_one(api: TestClient) -> None:
    first = api.post("/v1/books", json=book_payload()).json()["id"]
    second = api.post("/v1/books", json=book_payload()).json()["id"]

    assert UUID(first) != UUID(second)


def test_a_refused_duplicate_changes_nothing(api: TestClient) -> None:
    original = create_book(api, isbn=isbn_for(5), title="Original", copies=2)

    refused = api.post("/v1/books", json=book_payload(isbn=isbn_for(5), title="Impostor", copies=9))

    listed = api.get("/v1/books").json()
    assert refused.status_code == 409
    assert listed["total"] == 1
    assert listed["items"] == [original]


def test_the_409_names_the_isbn_it_refused_and_never_the_title(api: TestClient) -> None:
    create_book(api, isbn=isbn_for(5))

    refused = api.post("/v1/books", json=book_payload(isbn=isbn_for(5), title="Secret title"))

    assert isbn_for(5) in refused.json()["detail"]
    assert "Secret title" not in refused.text


@pytest.mark.parametrize("extra", ["isbn", "copies"])
def test_an_update_cannot_change_the_isbn_or_the_capacity(api: TestClient, extra: str) -> None:
    book = create_book(api, isbn=isbn_for(1), copies=2)
    payload = {"title": "New", "author": "Other", "isbn": isbn_for(2), "copies": 9}

    response = api.put(f"/v1/books/{book['id']}", json={**payload, "id": book["id"]})
    only_one = api.put(
        f"/v1/books/{book['id']}",
        json={"title": "New", "author": "Other", extra: payload[extra]},
    )

    assert response.status_code == 422
    assert only_one.status_code == 422
    assert [i["type"] for i in only_one.json()["errors"]] == ["extra_forbidden"]
    assert api.get(f"/v1/books/{book['id']}").json() == book


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"title": "", "author": "A"},
        {"title": "T", "author": ""},
        {"title": " ", "author": "A"},
        {"title": "T", "author": "  "},
        {"title": "t" * 201, "author": "A"},
        {"title": "T", "author": "a" * 201},
        {"title": None, "author": "A"},
        {"title": "T", "author": 5},
    ],
    ids=[
        "empty",
        "empty-title",
        "empty-author",
        "blank-title",
        "blank-author",
        "title-201",
        "author-201",
        "null",
        "number",
    ],
)
def test_an_invalid_update_is_a_422_and_changes_nothing(api: TestClient, payload: dict[str, Any]) -> None:
    book = create_book(api)

    response = api.put(f"/v1/books/{book['id']}", json=payload)

    assert response.status_code == 422
    assert api.get(f"/v1/books/{book['id']}").json() == book


BLANK_CHARACTERS = [
    *"\t\n\x0b\x0c\r \x85\xa0\u1680\u2028\u2029\u202f\u205f\u3000",
    *(chr(code) for code in range(0x2000, 0x200B)),
]
LOOKS_BLANK_BUT_IS_NOT = ["\x1c", "\x1f", "\u180e", "\u200b", "\ufeff"]


@pytest.mark.parametrize("field", ["title", "author"])
@pytest.mark.parametrize("character", BLANK_CHARACTERS, ids=lambda c: f"U+{ord(c):04X}")
def test_every_unicode_whitespace_character_alone_is_a_blank_title_or_author(
    api: TestClient, field: str, character: str
) -> None:
    response = api.post("/v1/books", json=book_payload(**{field: character * 3}))

    assert response.status_code == 422
    assert [i["loc"][:2] for i in response.json()["errors"]] == [["body", field]]


@pytest.mark.parametrize("character", LOOKS_BLANK_BUT_IS_NOT, ids=lambda c: f"U+{ord(c):04X}")
def test_a_character_that_is_not_unicode_whitespace_is_not_blank(api: TestClient, character: str) -> None:
    response = api.post("/v1/books", json=book_payload(title=character, author=character))

    assert response.status_code == 201


def test_the_published_pattern_and_the_validator_agree_on_every_character() -> None:
    """The schema must not call a title valid that the API rejects, or the reverse."""
    title = TypeAdapter(Title)
    # A lone surrogate is not text: pydantic refuses it as `string_unicode` before any rule runs.
    surrogates = range(0xD800, 0xE000)
    probed = [code for code in [*range(0x10000), *range(0x10000, sys.maxunicode + 1, 97)] if code not in surrogates]

    disagreements = []
    for code in probed:
        character = chr(code)
        try:
            title.validate_python(character)
            accepted = True
        except ValidationError:
            accepted = False
        if accepted != (re.search(NON_BLANK, character) is not None):
            disagreements.append(f"U+{code:04X}")

    assert disagreements == []


def test_surrounding_whitespace_is_dropped_from_a_title_and_an_author(api: TestClient) -> None:
    created = create_book(api, title="  Clean Code\n", author="\tR. Martin ")

    updated = api.put(f"/v1/books/{created['id']}", json={"title": " New \t", "author": "  Someone "}).json()

    assert (created["title"], created["author"]) == ("Clean Code", "R. Martin")
    assert (updated["title"], updated["author"]) == ("New", "Someone")
    assert api.get(f"/v1/books/{created['id']}").json() == updated


def test_validation_is_reported_before_the_book_is_looked_up(api: TestClient) -> None:
    response = api.put(f"/v1/books/{MISSING_ID}", json={"title": ""})

    assert response.status_code == 422


def test_an_update_on_the_edge_of_the_limits_is_accepted(api: TestClient) -> None:
    book = create_book(api)

    response = api.put(f"/v1/books/{book['id']}", json={"title": "t" * 200, "author": "a" * 200})

    assert response.status_code == 200
    assert (len(response.json()["title"]), len(response.json()["author"])) == (200, 200)


def test_an_update_keeps_the_place_of_the_book_in_the_list_and_is_repeatable(
    api: TestClient,
) -> None:
    books = [create_book(api, isbn=isbn_for(n)) for n in range(1, 4)]

    first = api.put(f"/v1/books/{books[0]['id']}", json={"title": "Z", "author": "Z"})
    second = api.put(f"/v1/books/{books[0]['id']}", json={"title": "Z", "author": "Z"})

    listed = api.get("/v1/books").json()
    assert first.json() == second.json()
    assert [b["id"] for b in listed["items"]] == [b["id"] for b in books]
    assert listed["total"] == 3


@pytest.mark.parametrize(
    "query",
    ["offset=1&offset=2", "offset=false&offset=0.0", "limit=5&limit=5", "offset=0&limit=5&limit=6"],
)
def test_a_paging_parameter_given_twice_is_a_422_not_the_last_value(api: TestClient, query: str) -> None:
    response = api.get(f"/v1/books?{query}")

    assert response.status_code == 422
    assert response.json()["errors"][0]["type"] == "repeated_parameter"


@pytest.mark.parametrize("limit", [1, 100])
def test_the_limits_of_the_page_size_are_accepted(api: TestClient, limit: int) -> None:
    create_book(api)

    response = api.get("/v1/books", params={"limit": limit})

    assert response.status_code == 200
    assert response.json()["limit"] == limit


def test_an_offset_at_or_past_the_end_is_an_empty_page_with_the_real_total(
    api: TestClient,
) -> None:
    for number in range(1, 4):
        create_book(api, isbn=isbn_for(number))

    at_end = api.get("/v1/books", params={"offset": 3}).json()
    far_past = api.get("/v1/books", params={"offset": 10**9, "limit": 100}).json()

    assert (at_end["items"], at_end["total"], at_end["offset"]) == ([], 3, 3)
    assert (far_past["items"], far_past["total"]) == ([], 3)


def test_walking_every_page_yields_each_book_once_in_creation_order(api: TestClient) -> None:
    created = [create_book(api, isbn=isbn_for(n))["id"] for n in range(1, 8)]

    walked: list[str] = []
    for offset in range(0, 8, 3):
        page = api.get("/v1/books", params={"limit": 3, "offset": offset}).json()
        assert page["total"] == 7
        walked += [b["id"] for b in page["items"]]

    assert walked == created


def test_a_page_larger_than_the_catalogue_returns_all_of_it(api: TestClient) -> None:
    for number in range(1, 4):
        create_book(api, isbn=isbn_for(number))

    body = api.get("/v1/books", params={"limit": 100}).json()

    assert (len(body["items"]), body["total"], body["limit"]) == (3, 3, 100)


@pytest.mark.parametrize(
    "query",
    ["limit=-1", "limit=1000", "limit=", "limit=1e1", "limit=0x10", "offset=", "offset=abc"],
)
def test_malformed_paging_is_a_422(api: TestClient, query: str) -> None:
    response = api.get(f"/v1/books?{query}")

    assert response.status_code == 422
    assert response.json()["errors"][0]["loc"][0] == "query"


def test_the_configured_page_size_applies_when_no_limit_is_given() -> None:
    client = TestClient(create_app(make_settings(default_page_size=5)))
    for number in range(1, 8):
        client.post("/v1/books", json=book_payload(isbn=isbn_for(number)))

    body = client.get("/v1/books").json()

    assert (len(body["items"]), body["limit"], body["total"]) == (5, 5, 7)
    assert len(client.get("/v1/books", params={"limit": 7}).json()["items"]) == 7


def test_successful_book_responses_are_application_json(api: TestClient) -> None:
    created = api.post("/v1/books", json=book_payload())

    for response in (created, api.get("/v1/books"), api.get(created.headers["Location"])):
        assert response.headers["content-type"] == "application/json"
