"""The extractions endpoints, through HTTP, a real SQLite file and a fake parser and model."""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

from formlens.config import Settings
from formlens.extractions.domain.exceptions import InvalidOutput, LlmUnavailable
from formlens.extractions.domain.model import Extraction, ExtractionStatus
from formlens.extractions.service_layer.processor import ExtractionProcessor
from formlens.main import create_app
from formlens.problems import PROBLEM_MEDIA_TYPE
from tests.conftest import make_settings
from tests.documents import png_of_size, sample
from tests.extractions.fakes import FakeExtractor
from tests.fakes import FakeParser
from tests.templates.factories import field_body, template_body

URL = "/v1/extractions"
PDF = sample("text_layer.pdf")


def problem_type(slug: str) -> str:
    return f"urn:problem:formlens:{slug}"


def make_template(client: TestClient, **overrides: Any) -> dict[str, Any]:
    body = template_body(
        name="Invoice",
        fields=[field_body(name="number", required=True), field_body(name="buyer")],
        **overrides,
    )
    response = client.post("/v1/templates", json=body)
    assert response.status_code == 201
    created: dict[str, Any] = response.json()
    return created


def submit(client: TestClient, template_id: str, content: bytes = PDF, **kwargs: Any) -> Any:
    return client.post(
        URL, data={"template_id": template_id}, files={"file": ("form.pdf", content, "application/pdf")}, **kwargs
    )


def processor(app: FastAPI) -> ExtractionProcessor:
    return app.state.extraction_processor  # type: ignore[no-any-return]  # set by the lifespan


@pytest.fixture
def extractor() -> FakeExtractor:
    return FakeExtractor({"number": "INV-42", "buyer": "ACME"})


@pytest.fixture
def app(settings: Settings, extractor: FakeExtractor) -> Any:
    application = create_app(
        settings, parser_factory=lambda _: FakeParser(), extractor_factory=lambda _: extractor, start_worker=False
    )
    yield application
    application.state.database.dispose()


# --- submit and read -------------------------------------------------------------------------------


def test_a_submitted_document_is_accepted_with_202_and_a_location_and_is_pending(client: TestClient) -> None:
    template = make_template(client)

    response = submit(client, template["id"])

    body = response.json()
    assert response.status_code == 202
    assert response.headers["Location"] == f"{URL}/{body['id']}"
    assert UUID(body["id"]).version == 7
    assert (body["status"], body["attempts"], body["template_id"], body["template_version"]) == (
        "pending",
        0,
        template["id"],
        1,
    )
    assert (body["result"], body["error"], body["missing_required"]) == (None, None, [])
    assert client.get(response.headers["Location"]).json() == body


def test_a_job_goes_from_pending_to_completed_with_a_result_that_fits_the_template(
    app: FastAPI, client: TestClient
) -> None:
    template = make_template(client)
    location = submit(client, template["id"]).headers["Location"]

    assert processor(app).run_once() is True

    done = client.get(location).json()
    assert done["status"] == "completed"
    assert done["attempts"] == 1
    assert done["result"] == {"number": "INV-42", "buyer": "ACME"}
    assert Draft202012Validator(template["json_schema"]).is_valid(done["result"])
    assert (done["started_at"], done["finished_at"]) != (None, None)
    assert (done["error"], done["missing_required"]) == (None, [])


def test_ten_documents_complete_one_after_another_each_with_a_result_that_fits_the_schema(
    app: FastAPI, client: TestClient
) -> None:
    template = make_template(client)
    locations = [submit(client, template["id"]).headers["Location"] for _ in range(10)]
    assert {client.get(location).json()["status"] for location in locations} == {"pending"}
    validator = Draft202012Validator(template["json_schema"])

    steps = [processor(app).run_once() for _ in range(11)]

    assert steps == [True] * 10 + [False]
    results = [client.get(location).json() for location in locations]
    assert {item["status"] for item in results} == {"completed"}
    assert all(validator.is_valid(item["result"]) for item in results)
    assert [item["id"] for item in results] == [location.rsplit("/", 1)[1] for location in locations]


def test_a_null_in_a_required_field_is_still_completed_and_is_listed_as_missing(
    app: FastAPI, client: TestClient, extractor: FakeExtractor
) -> None:
    extractor.values = {"number": None, "buyer": "ACME"}
    template = make_template(client)
    location = submit(client, template["id"]).headers["Location"]

    processor(app).run_once()

    done = client.get(location).json()
    assert done["status"] == "completed"
    assert done["result"] == {"number": None, "buyer": "ACME"}
    assert done["missing_required"] == ["number"]


def test_a_failed_job_reports_a_reason_and_a_fixed_message_and_no_result(
    app: FastAPI, client: TestClient, extractor: FakeExtractor
) -> None:
    extractor.errors = [InvalidOutput("schema"), InvalidOutput("schema")]
    template = make_template(client)
    location = submit(client, template["id"]).headers["Location"]

    processor(app).run_once()
    assert client.get(location).json()["status"] == "pending"  # the first attempt is retried
    processor(app).run_once()

    failed = client.get(location).json()
    assert (failed["status"], failed["attempts"], failed["result"]) == ("failed", 2, None)
    assert failed["error"] == {
        "reason": "invalid_output",
        "message": "The language model did not return a result that fits the template.",
    }


def test_a_model_that_is_down_fails_the_job_after_the_attempts_without_losing_it_meanwhile(
    app: FastAPI, client: TestClient, extractor: FakeExtractor
) -> None:
    extractor.errors = [LlmUnavailable("ConnectError"), LlmUnavailable("ConnectError")]
    template = make_template(client)
    location = submit(client, template["id"]).headers["Location"]

    processor(app).run_once()
    processor(app).run_once()

    assert client.get(location).json()["error"]["reason"] == "llm_unavailable"


# --- the template is copied at submit time ---------------------------------------------------------


def test_editing_the_template_after_submit_does_not_change_the_queued_job(
    app: FastAPI, client: TestClient, extractor: FakeExtractor
) -> None:
    template = make_template(client)
    location = submit(client, template["id"]).headers["Location"]
    client.put(
        f"/v1/templates/{template['id']}",
        json=template_body(name="Invoice 2", fields=[field_body(name="other", required=True)]),
    )

    processor(app).run_once()

    done = client.get(location).json()
    assert done["template_version"] == 1
    assert sorted(done["result"]) == ["buyer", "number"]  # the fields of version 1, not of version 2
    assert extractor.calls[0][1] == UUID(template["id"])


def test_deleting_the_template_after_submit_does_not_stop_the_job(app: FastAPI, client: TestClient) -> None:
    template = make_template(client)
    location = submit(client, template["id"]).headers["Location"]
    assert client.delete(f"/v1/templates/{template['id']}").status_code == 204

    processor(app).run_once()

    assert client.get(location).json()["status"] == "completed"


# --- refusals --------------------------------------------------------------------------------------


def test_an_unknown_template_is_a_404_template_not_found_and_nothing_is_queued(client: TestClient) -> None:
    response = submit(client, str(uuid4()))

    assert response.status_code == 404
    assert response.headers["content-type"] == PROBLEM_MEDIA_TYPE
    assert response.json()["type"] == problem_type("template-not-found")


def test_an_empty_file_is_a_400_invalid_file(client: TestClient) -> None:
    template = make_template(client)

    response = submit(client, template["id"], b"")

    assert (response.status_code, response.json()["type"]) == (400, problem_type("invalid-file"))


def test_a_file_that_is_not_a_document_is_a_415(client: TestClient) -> None:
    template = make_template(client)

    response = submit(client, template["id"], b"just some text")

    assert (response.status_code, response.json()["type"]) == (415, problem_type("unsupported-media-type"))


@pytest.mark.parametrize("size", [1024 * 1024 + 1, 3 * 1024 * 1024], ids=["over-the-limit", "over-the-body-cap"])
def test_a_file_over_the_limit_is_a_413(db_url: str, size: int) -> None:
    app = create_app(
        make_settings(db_url=db_url, max_upload_mb=1),
        parser_factory=lambda _: FakeParser(),
        extractor_factory=lambda _: FakeExtractor(),
        start_worker=False,
    )
    try:
        with TestClient(app) as client:
            template = make_template(client)
            response = submit(client, template["id"], png_of_size(size))
    finally:
        app.state.database.dispose()

    assert (response.status_code, response.json()["type"]) == (413, problem_type("file-too-large"))


@pytest.mark.parametrize(
    "data",
    [{}, {"template_id": "not-a-uuid"}],
    ids=["no-template-id", "template-id-not-a-uuid"],
)
def test_a_missing_or_malformed_template_id_is_a_422(client: TestClient, data: dict[str, str]) -> None:
    response = client.post(URL, data=data, files={"file": ("a.pdf", PDF, "application/pdf")})

    assert response.status_code == 422
    assert response.json()["type"] == problem_type("validation-error")


def test_a_request_without_a_file_is_a_422(client: TestClient) -> None:
    template = make_template(client)

    response = client.post(URL, data={"template_id": template["id"]})

    assert response.status_code == 422


def test_an_unknown_extraction_is_a_404_extraction_not_found(client: TestClient) -> None:
    response = client.get(f"{URL}/{uuid4()}")

    assert response.status_code == 404
    assert response.json()["type"] == problem_type("extraction-not-found")


def test_an_extraction_id_that_is_not_a_uuid_is_a_422(client: TestClient) -> None:
    response = client.get(f"{URL}/not-a-uuid")

    assert (response.status_code, response.json()["type"]) == (422, problem_type("validation-error"))


def test_a_result_older_than_its_time_to_live_is_a_404_even_before_the_purge(app: FastAPI, client: TestClient) -> None:
    template = make_template(client)
    location = submit(client, template["id"]).headers["Location"]
    repository = app.state.extraction_repository
    taken = repository.claim_next(datetime.now(UTC))
    ended = taken.complete({"number": "x", "buyer": None}, datetime.now(UTC) - timedelta(hours=25))
    assert repository.finish_if_running(ended) is True

    response = client.get(location)

    assert (response.status_code, response.json()["type"]) == (404, problem_type("extraction-not-found"))


# --- the queue -------------------------------------------------------------------------------------


def test_a_full_queue_is_a_503_queue_full_with_retry_after_and_a_free_place_opens_when_a_job_ends(
    db_url: str,
) -> None:
    app = create_app(
        make_settings(db_url=db_url, queue_max_pending=2),
        parser_factory=lambda _: FakeParser(),
        extractor_factory=lambda _: FakeExtractor(),
        start_worker=False,
    )
    try:
        with TestClient(app) as client:
            template = make_template(client)
            assert [submit(client, template["id"]).status_code for _ in range(2)] == [202, 202]

            full = submit(client, template["id"])
            processor(app).run_once()
            again = submit(client, template["id"])
    finally:
        app.state.database.dispose()

    assert full.status_code == 503
    assert full.headers["Retry-After"] == "30"
    assert full.json()["type"] == problem_type("queue-full")
    assert again.status_code == 202


def test_a_browser_may_read_the_location_header(db_url: str) -> None:
    origin = "https://app.example.com"
    app = create_app(
        make_settings(db_url=db_url, cors_origins=[origin]),
        parser_factory=lambda _: FakeParser(),
        extractor_factory=lambda _: FakeExtractor(),
        start_worker=False,
    )
    try:
        with TestClient(app) as client:
            template = make_template(client)
            response = client.post(
                URL,
                data={"template_id": template["id"]},
                files={"file": ("a.pdf", PDF, "application/pdf")},
                headers={"Origin": origin},
            )
    finally:
        app.state.database.dispose()

    exposed = response.headers["access-control-expose-headers"]
    assert "Location" in exposed
    assert "Retry-After" in exposed


# --- the spec --------------------------------------------------------------------------------------


def test_the_two_routes_are_in_the_spec_with_their_statuses(client: TestClient) -> None:
    spec = client.app.openapi()  # type: ignore[attr-defined]  # the app of the client

    post = spec["paths"]["/v1/extractions"]["post"]
    get = spec["paths"]["/v1/extractions/{extraction_id}"]["get"]
    assert (post["operationId"], get["operationId"]) == ("create_extraction", "get_extraction")
    assert sorted(post["responses"]) == ["202", "400", "404", "413", "415", "422", "503"]
    assert "Location" in post["responses"]["202"]["headers"]
    assert "Retry-After" in post["responses"]["503"]["headers"]
    assert sorted(get["responses"]) == ["200", "404", "422"]


def test_the_response_has_no_field_for_the_document_or_the_prompt(client: TestClient) -> None:
    schema = client.app.openapi()["components"]["schemas"]["ExtractionResponse"]  # type: ignore[attr-defined]

    assert set(schema["properties"]) == {
        "id",
        "status",
        "template_id",
        "template_version",
        "result",
        "missing_required",
        "error",
        "attempts",
        "created_at",
        "started_at",
        "finished_at",
    }


def test_the_extraction_state_is_exactly_what_the_repository_holds(app: FastAPI, client: TestClient) -> None:
    template = make_template(client)
    body = submit(client, template["id"]).json()

    stored: Extraction | None = app.state.extraction_repository.get(UUID(body["id"]))

    assert stored is not None
    assert stored.status is ExtractionStatus.PENDING
    assert body["id"] == str(stored.id)
