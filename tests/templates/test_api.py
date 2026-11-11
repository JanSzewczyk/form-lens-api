"""The templates endpoints, through HTTP and a real SQLite file."""

import json
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.testclient import TestClient as StarletteTestClient

from formlens.config import Settings
from formlens.logging_config import configure_logging
from formlens.main import create_app
from formlens.patterns import matches
from formlens.problems import PROBLEM_MEDIA_TYPE
from formlens.templates.json_schema import build_json_schema
from formlens.templates.models import FieldType, TemplateField
from tests.conftest import make_settings
from tests.fakes import FakeParser
from tests.templates.factories import field_body, template_body

URL = "/v1/templates"


def create(client: TestClient, **overrides: Any) -> dict[str, Any]:
    response = client.post(URL, json=template_body(**overrides))
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


def problem_type(slug: str) -> str:
    return f"urn:problem:formlens:{slug}"


# --- create ----------------------------------------------------------------------------------------


def test_creating_a_template_returns_201_with_version_one_and_the_generated_schema(client: TestClient) -> None:
    response = client.post(
        URL,
        json={
            "name": "Invoice",
            "description": "Supplier invoice",
            "fields": [
                field_body(name="invoice_number", description="Top right", required=True),
                field_body(name="total", type="number", minimum=0, maximum=1000),
                field_body(name="state", type="choice", allowed_values=["paid", "unpaid"]),
            ],
        },
    )

    body = response.json()
    assert response.status_code == 201
    assert (body["name"], body["description"], body["version"]) == ("Invoice", "Supplier invoice", 1)
    assert UUID(body["id"]).version == 7
    assert [item["name"] for item in body["fields"]] == ["invoice_number", "total", "state"]
    assert body["fields"][0] == {
        "name": "invoice_number",
        "type": "text",
        "description": "Top right",
        "required": True,
        "allowed_values": None,
        "minimum": None,
        "maximum": None,
        "pattern": None,
    }
    expected_fields = [
        TemplateField("invoice_number", FieldType.TEXT, description="Top right", required=True),
        TemplateField("total", FieldType.NUMBER, minimum=0, maximum=1000),
        TemplateField("state", FieldType.CHOICE, allowed_values=("paid", "unpaid")),
    ]
    assert body["json_schema"] == build_json_schema(expected_fields)
    assert body["created_at"] == body["updated_at"]


def test_a_created_template_can_be_read_back_unchanged(client: TestClient) -> None:
    created = create(client, name="Roundtrip", fields=[field_body(name="when", type="date", required=True)])

    response = client.get(f"{URL}/{created['id']}")

    assert response.status_code == 200
    assert response.json() == created


def test_a_template_is_still_there_after_the_app_is_rebuilt_on_the_same_database(
    client: TestClient, settings: Settings
) -> None:
    created = create(client, name="Durable")
    other = create_app(settings, parser_factory=lambda _: FakeParser())
    try:
        response = StarletteTestClient(other).get(f"{URL}/{created['id']}")
    finally:
        other.state.database.dispose()

    assert response.json()["name"] == "Durable"


@pytest.mark.parametrize(
    ("overrides", "rule"),
    [
        pytest.param(
            {"fields": [field_body(name="a"), field_body(name="a")]},
            "Field a: field names must be unique",
            id="duplicate",
        ),
        pytest.param(
            {"fields": [field_body(name="a", allowed_values=["x"])]},
            "Field a: allowed_values is only for",
            id="values-on-text",
        ),
        pytest.param(
            {"fields": [field_body(name="a", type="choice")]},
            "Field a: the type choice needs allowed_values",
            id="choice-without-values",
        ),
        pytest.param(
            {"fields": [field_body(name="a", minimum=1)]},
            "Field a: minimum and maximum are only for",
            id="range-on-text",
        ),
        pytest.param(
            {"fields": [field_body(name="a", type="number", minimum=2, maximum=1)]},
            "Field a: minimum is greater than maximum",
            id="range-reversed",
        ),
        pytest.param(
            {"fields": [field_body(name="a", pattern="(")]}, "Field a: pattern is not a valid", id="bad-pattern"
        ),
        pytest.param({"name": " "}, "name must be 1 to 100", id="blank-name"),
    ],
)
def test_a_template_that_breaks_a_rule_is_a_422_invalid_template_naming_the_rule(
    client: TestClient, overrides: dict[str, Any], rule: str
) -> None:
    response = client.post(URL, json=template_body(**overrides))

    body = response.json()
    assert response.status_code == 422
    assert response.headers["content-type"] == PROBLEM_MEDIA_TYPE
    assert body["type"] == problem_type("invalid-template")
    assert body["title"] == "Invalid template"
    assert rule in body["detail"]
    assert client.get(URL).json()["total"] == 0


def test_the_422_for_a_rule_never_repeats_a_value_of_the_request(client: TestClient) -> None:
    marker = "MARKER-8841"
    response = client.post(
        URL,
        json=template_body(fields=[field_body(name="a", pattern=marker + "(", description=marker)]),
    )

    assert response.status_code == 422
    assert marker not in response.text


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({"name": "x"}, id="fields-missing"),
        pytest.param({"fields": [field_body()]}, id="name-missing"),
        pytest.param(template_body(fields=[field_body(type="barcode")]), id="unknown-type"),
        pytest.param(template_body(fields=[{"type": "text"}]), id="field-name-missing"),
        pytest.param(template_body(unknown=1), id="unknown-key"),
        pytest.param(template_body(fields=[field_body(minimum="low", type="number")]), id="range-not-a-number"),
        pytest.param(template_body(name=5), id="name-not-text"),
        pytest.param(template_body(fields=[]), id="no-fields"),
        pytest.param(template_body(fields=[field_body(name=f"f{i}") for i in range(51)]), id="too-many-fields"),
        pytest.param(template_body(fields=[field_body(name="__proto__")]), id="unsafe-key"),
        pytest.param(template_body(fields=[field_body(name="Upper")]), id="capital-in-key"),
        pytest.param(template_body(fields=[field_body(pattern="x" * 201)]), id="long-pattern"),
        pytest.param(template_body(fields=[field_body(type="choice", allowed_values=[""])]), id="blank-choice-value"),
        pytest.param(template_body(name=""), id="empty-name"),
        pytest.param(template_body(name="n" * 101), id="long-name"),
        pytest.param([], id="not-an-object"),
    ],
)
def test_a_body_of_the_wrong_shape_is_a_422_validation_error(client: TestClient, body: Any) -> None:
    response = client.post(URL, json=body)

    assert response.status_code == 422
    assert response.json()["type"] == problem_type("validation-error")


def test_a_body_that_is_not_json_is_a_422_and_one_that_is_not_text_is_a_400(client: TestClient) -> None:
    headers = {"Content-Type": "application/json"}

    not_json = client.post(URL, content=b"{not json", headers=headers)
    not_text = client.post(URL, content=b"\xff\xfe\x00", headers=headers)

    assert not_json.status_code == 422
    assert not_json.json()["errors"][0]["type"] == "json_invalid"
    assert not_text.status_code == 400


def test_a_json_string_with_a_lone_surrogate_is_a_422_not_a_500(client: TestClient) -> None:
    body = b'{"name": "\\ud800", "fields": [{"name": "a", "type": "text"}]}'

    response = client.post(URL, content=body, headers={"Content-Type": "application/json"})

    assert response.status_code == 422
    assert response.json()["type"] == problem_type("validation-error")


def test_a_regular_expression_the_engine_cannot_compile_is_a_422_not_a_500(client: TestClient) -> None:
    response = client.post(URL, json=template_body(fields=[field_body(pattern="a{4294967295}")]))

    assert response.status_code == 422
    assert response.json()["type"] == problem_type("invalid-template")


def test_a_not_a_number_in_a_range_is_refused(client: TestClient) -> None:
    response = client.post(
        URL,
        content=b'{"name": "x", "fields": [{"name": "a", "type": "number", "minimum": NaN}]}',
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 422


# --- read ------------------------------------------------------------------------------------------


def test_an_unknown_template_is_a_404_template_not_found(client: TestClient) -> None:
    response = client.get(f"{URL}/{uuid4()}")

    assert response.status_code == 404
    assert response.headers["content-type"] == PROBLEM_MEDIA_TYPE
    assert response.json()["type"] == problem_type("template-not-found")


def test_an_id_that_is_not_a_uuid_is_a_422(client: TestClient) -> None:
    response = client.get(f"{URL}/not-a-uuid")

    assert response.status_code == 422
    assert response.json()["type"] == problem_type("validation-error")


def test_listing_an_empty_database_returns_an_empty_page(client: TestClient) -> None:
    response = client.get(URL)

    assert response.json() == {"items": [], "total": 0, "limit": 20, "offset": 0}


def test_templates_are_listed_oldest_first_one_page_at_a_time(client: TestClient) -> None:
    names = [create(client, name=f"Form {i}")["name"] for i in range(5)]

    first = client.get(URL, params={"limit": 2}).json()
    second = client.get(URL, params={"limit": 2, "offset": 2}).json()
    last = client.get(URL, params={"limit": 2, "offset": 4}).json()
    beyond = client.get(URL, params={"limit": 2, "offset": 10}).json()

    assert [item["name"] for item in first["items"]] == names[0:2]
    assert [item["name"] for item in second["items"]] == names[2:4]
    assert [item["name"] for item in last["items"]] == names[4:5]
    assert beyond["items"] == []
    assert (first["total"], second["total"], last["total"], beyond["total"]) == (5, 5, 5, 5)
    assert (second["limit"], second["offset"]) == (2, 2)


def test_the_default_page_size_comes_from_the_settings(settings: Settings) -> None:
    app: FastAPI = create_app(
        settings.model_copy(update={"default_page_size": 3}), parser_factory=lambda _: FakeParser()
    )
    try:
        client = StarletteTestClient(app)
        for i in range(4):
            create(client, name=f"Form {i}")

        page = client.get(URL).json()
    finally:
        app.state.database.dispose()

    assert (len(page["items"]), page["total"], page["limit"]) == (3, 4, 3)


@pytest.mark.parametrize(
    "params",
    [{"limit": 0}, {"limit": 101}, {"offset": -1}, {"limit": "many"}],
    ids=["zero", "over-max", "negative-offset", "text"],
)
def test_a_bad_page_request_is_a_422(client: TestClient, params: dict[str, Any]) -> None:
    assert client.get(URL, params=params).status_code == 422


# --- replace ---------------------------------------------------------------------------------------


def test_replacing_a_template_returns_the_next_version_with_the_new_content(client: TestClient) -> None:
    created = create(client, name="Before", fields=[field_body(name="old")])

    response = client.put(
        f"{URL}/{created['id']}",
        json=template_body(name="After", description="Changed", fields=[field_body(name="fresh", type="integer")]),
    )

    body = response.json()
    assert response.status_code == 200
    assert (body["id"], body["version"], body["name"], body["description"]) == (created["id"], 2, "After", "Changed")
    assert [(item["name"], item["type"]) for item in body["fields"]] == [("fresh", "integer")]
    assert body["json_schema"]["required"] == ["fresh"]
    assert body["created_at"] == created["created_at"]
    assert body["updated_at"] >= created["updated_at"]
    assert client.get(f"{URL}/{created['id']}").json() == body


def test_each_replacement_raises_the_version_by_one(client: TestClient) -> None:
    created = create(client)

    versions = [
        client.put(f"{URL}/{created['id']}", json=template_body(name=f"v{i}")).json()["version"] for i in range(3)
    ]

    assert versions == [2, 3, 4]


def test_replacing_an_unknown_template_is_a_404(client: TestClient) -> None:
    response = client.put(f"{URL}/{uuid4()}", json=template_body())

    assert response.status_code == 404
    assert response.json()["type"] == problem_type("template-not-found")


def test_an_invalid_replacement_changes_nothing_and_keeps_the_version(client: TestClient) -> None:
    created = create(client, name="Stable")

    duplicated = [field_body(name="same"), field_body(name="same")]
    response = client.put(f"{URL}/{created['id']}", json=template_body(fields=duplicated))

    assert response.status_code == 422
    assert response.json()["type"] == problem_type("invalid-template")
    assert client.get(f"{URL}/{created['id']}").json() == created


def test_a_replacement_with_a_body_of_the_wrong_shape_is_a_422_validation_error(client: TestClient) -> None:
    created = create(client)

    response = client.put(f"{URL}/{created['id']}", json={"name": "x"})

    assert response.status_code == 422
    assert response.json()["type"] == problem_type("validation-error")


# --- delete ----------------------------------------------------------------------------------------


def test_deleting_a_template_returns_204_without_a_body_and_removes_it(client: TestClient) -> None:
    created = create(client)

    response = client.delete(f"{URL}/{created['id']}")

    assert (response.status_code, response.content) == (204, b"")
    assert client.get(f"{URL}/{created['id']}").status_code == 404
    assert client.get(URL).json()["total"] == 0


def test_deleting_an_unknown_or_an_already_deleted_template_is_a_404(client: TestClient) -> None:
    created = create(client)
    client.delete(f"{URL}/{created['id']}")

    again = client.delete(f"{URL}/{created['id']}")
    unknown = client.delete(f"{URL}/{uuid4()}")

    assert again.status_code == unknown.status_code == 404
    assert unknown.json()["type"] == problem_type("template-not-found")


# --- logging ---------------------------------------------------------------------------------------


def test_creating_a_template_logs_its_id_and_size_but_not_its_content(
    client: TestClient, capsys: pytest.CaptureFixture[str]
) -> None:

    configure_logging(make_settings(log_format="json"))
    marker = "MARKER-4417"

    created = create(client, name=marker, fields=[field_body(name="a", description=marker)])

    out = capsys.readouterr().out
    assert "template_created" in out
    assert created["id"] in out
    assert marker not in out


# --- patterns the matching engine runs ---------------------------------------------------------------


@pytest.mark.parametrize(
    "pattern",
    ["(?=a)a", "(?!a)b", "(?<=a)b", r"(a)\1", r"a\Z", "[[a]"],
    ids=["lookahead", "negative-lookahead", "lookbehind", "backreference", "python-only-escape", "python-only-class"],
)
def test_a_pattern_the_matching_engine_cannot_compile_is_refused_at_creation(client: TestClient, pattern: str) -> None:
    """`re` compiles all of these and `formlens.patterns.check_pattern` refuses them, so a template that stores one
    fails every job it is used for (`invalid_output`, after every attempt). The spec says "no lookahead, lookbehind
    or backreference" and the hand-off says they are refused at creation."""
    response = client.post(URL, json=template_body(fields=[field_body(name="a", pattern=pattern)]))

    assert response.status_code == 422
    assert response.json()["type"] == problem_type("invalid-template")
    assert client.get(URL).json()["total"] == 0


def test_a_pattern_the_matching_engine_runs_is_not_refused_by_the_validator(client: TestClient) -> None:
    """The validator (`re`) calls `\\p{L}+` invalid and the matcher (`pydantic-core`) runs it: they disagree.
    Weaker than the defect above: a refusal of a runnable pattern costs the client a workaround, not a job."""
    assert matches(r"\p{L}+", "zażółć") is True  # the matcher's verdict, as the worker uses it

    response = client.post(URL, json=template_body(fields=[field_body(name="a", pattern=r"\p{L}+")]))

    assert response.status_code == 201


# --- input types -----------------------------------------------------------------------------------


@pytest.mark.parametrize("required", ["yes", "true", 1, 0], ids=["yes", "true-string", "one", "zero"])
def test_required_is_a_json_boolean_and_nothing_that_merely_reads_like_one(client: TestClient, required: Any) -> None:
    response = client.post(URL, json=template_body(fields=[field_body(name="a", required=required)]))

    assert response.status_code == 422
    assert response.json()["type"] == problem_type("validation-error")


def test_text_in_any_script_survives_a_round_trip_in_every_text_field(client: TestClient) -> None:
    body = template_body(
        name="Zażółć gęślą jaźń 😀",
        description="説明 — ünïcödé",
        fields=[
            field_body(name="state", type="choice", description="Stan", allowed_values=["tak ✓", "nie ✗", "może"]),
            field_body(name="city", pattern="^[a-zżółćęśńźą ]+$"),
        ],
    )

    created = client.post(URL, json=body)
    read = client.get(f"{URL}/{created.json()['id']}")

    assert created.status_code == 201
    assert [read.json()[key] for key in ("name", "description")] == [body["name"], body["description"]]
    assert read.json()["fields"][0]["allowed_values"] == ["tak ✓", "nie ✗", "może"]
    assert read.json()["json_schema"]["properties"]["state"]["enum"] == ["tak ✓", "nie ✗", "może", None]


@pytest.mark.parametrize("content_type", ["text/plain", "application/x-www-form-urlencoded", "application/xml"])
def test_a_valid_body_sent_with_the_wrong_content_type_is_a_422_and_stores_nothing(
    client: TestClient, content_type: str
) -> None:
    response = client.post(URL, content=json.dumps(template_body()), headers={"Content-Type": content_type})

    assert response.status_code == 422
    assert response.headers["content-type"] == PROBLEM_MEDIA_TYPE
    assert client.get(URL).json()["total"] == 0


def test_the_largest_page_is_accepted_and_one_more_is_not(client: TestClient) -> None:
    create(client, name="Only")

    assert client.get(URL, params={"limit": 100}).json()["limit"] == 100
    assert client.get(URL, params={"limit": 101}).status_code == 422


@pytest.mark.parametrize(
    ("method", "path", "allowed"),
    [
        pytest.param("PATCH", "/v1/templates", "GET, POST", id="collection-patch"),
        pytest.param("DELETE", "/v1/templates", "GET, POST", id="collection-delete"),
        pytest.param("PUT", "/v1/templates", "GET, POST", id="collection-put"),
        pytest.param("POST", f"/v1/templates/{UUID(int=1)}", "DELETE, GET, PUT", id="item-post"),
        pytest.param("PATCH", f"/v1/templates/{UUID(int=1)}", "DELETE, GET, PUT", id="item-patch"),
        pytest.param("POST", "/v1/templates/not-a-uuid", "DELETE, GET, PUT", id="item-post-bad-id"),
    ],
)
def test_a_wrong_method_on_a_templates_path_is_a_405_listing_every_method_of_the_path(
    client: TestClient, method: str, path: str, allowed: str
) -> None:
    response = client.request(method, path)

    assert response.status_code == 405
    assert sorted(response.headers["Allow"].split(", ")) == sorted(allowed.split(", "))
    assert response.headers["content-type"] == PROBLEM_MEDIA_TYPE


@pytest.mark.parametrize("path", ["/v1/templates/", f"/v1/templates/{UUID(int=1)}/"])
def test_a_trailing_slash_on_a_templates_path_is_a_404_problem_not_a_redirect(client: TestClient, path: str) -> None:
    response = client.get(path, follow_redirects=False)

    assert response.status_code == 404
    assert response.headers["content-type"] == PROBLEM_MEDIA_TYPE


@pytest.mark.parametrize("limit", ["minimum", "maximum"])
@pytest.mark.parametrize("value", ["5", True, "1e3"], ids=["numeric-string", "boolean", "exponent-string"])
def test_a_range_limit_is_a_json_number_and_nothing_that_merely_reads_like_one(
    client: TestClient, limit: str, value: Any
) -> None:
    response = client.post(URL, json=template_body(fields=[field_body(name="a", type="number", **{limit: value})]))

    assert response.status_code == 422
    assert response.json()["type"] == problem_type("validation-error")


def test_a_range_limit_written_as_a_whole_number_is_still_accepted(client: TestClient) -> None:
    response = client.post(URL, json=template_body(fields=[field_body(name="a", type="number", minimum=0, maximum=10)]))

    assert response.status_code == 201


def test_a_nul_character_in_a_name_is_a_422_invalid_template(client: TestClient) -> None:
    response = client.post(URL, json=template_body(name="Order\u0000form"))

    assert (response.status_code, response.json()["type"]) == (422, problem_type("invalid-template"))


# --- the cap on the body ---------------------------------------------------------------------------


def big_body(kilobytes: int) -> bytes:
    """A JSON object of about this many kilobytes, as the template routes would read it."""
    return json.dumps({"name": "x" * (kilobytes * 1024), "fields": []}).encode()


@pytest.mark.parametrize("method", ["post", "put"])
def test_a_template_body_over_the_limit_is_a_413_body_too_large_and_nothing_is_stored(db_url: str, method: str) -> None:
    app = create_app(
        make_settings(db_url=db_url, max_json_body_kb=4), parser_factory=lambda _: FakeParser(), start_worker=False
    )
    try:
        with TestClient(app) as client:
            created = create(client)
            url = URL if method == "post" else f"{URL}/{created['id']}"
            response = client.request(method, url, content=big_body(8), headers={"Content-Type": "application/json"})
            listed = client.get(URL).json()
    finally:
        app.state.database.dispose()

    assert response.status_code == 413
    assert response.headers["content-type"] == PROBLEM_MEDIA_TYPE
    assert response.json()["type"] == problem_type("body-too-large")
    assert response.json()["detail"] == "The request body is larger than the 4 KB limit."
    assert listed["total"] == 1  # only the one made above


def test_a_chunked_template_body_over_the_limit_is_a_413(db_url: str) -> None:
    app = create_app(
        make_settings(db_url=db_url, max_json_body_kb=4), parser_factory=lambda _: FakeParser(), start_worker=False
    )
    try:
        with TestClient(app) as client:
            response = client.post(
                URL,
                content=(piece for piece in (big_body(8)[:3000], big_body(8)[3000:])),  # no Content-Length
                headers={"Content-Type": "application/json"},
            )
    finally:
        app.state.database.dispose()

    assert (response.status_code, response.json()["type"]) == (413, problem_type("body-too-large"))


def test_a_template_body_under_the_limit_is_read_as_before(client: TestClient) -> None:
    assert client.post(URL, json=template_body()).status_code == 201


def test_the_default_limit_is_large_enough_for_the_largest_valid_template(client: TestClient) -> None:
    fields = [field_body(name=f"f{i}", description="d" * 300) for i in range(50)]

    response = client.post(URL, json=template_body(fields=fields))

    assert response.status_code == 201


def test_a_get_or_a_delete_has_no_body_cap_and_a_413_is_documented_on_both_writes(client: TestClient) -> None:
    spec = client.app.openapi()  # type: ignore[attr-defined]  # the app of the client

    assert "413" in spec["paths"]["/v1/templates"]["post"]["responses"]
    assert "413" in spec["paths"]["/v1/templates/{template_id}"]["put"]["responses"]
    assert "413" not in spec["paths"]["/v1/templates/{template_id}"]["get"]["responses"]
    assert "413" not in spec["paths"]["/v1/templates/{template_id}"]["delete"]["responses"]
