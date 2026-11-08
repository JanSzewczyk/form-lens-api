"""POST /v1/documents/parse through the HTTP test client, with a fake parser."""

import json
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx2 import Response

from formlens.config import Settings
from formlens.main import create_app
from formlens.parsing.exceptions import InvalidFile, ParseFailed
from formlens.parsing.models import BYTES_PER_MB
from formlens.parsing.ports import ParseResult
from tests.conftest import make_settings
from tests.documents import MULTIPART, multipart_body, multipart_chunks, png_of_size, sample
from tests.fakes import FakeParser

URL = "/v1/documents/parse"
PROBLEM = "application/problem+json"
TYPE = "urn:problem:formlens:"


def post_file(
    client: TestClient, content: bytes, *, name: str = "scan.png", params: dict[str, str] | None = None
) -> Response:
    return client.post(URL, files={"file": (name, content, "application/octet-stream")}, params=params)


@pytest.fixture
def settings() -> Settings:
    return make_settings(max_upload_mb=1)


class TestParsing:
    @pytest.mark.parametrize(
        ("name", "neutral"),
        [
            ("text_layer.pdf", "upload.pdf"),
            ("scan.pdf", "upload.pdf"),
            ("sample.png", "upload.png"),
            ("sample.jpg", "upload.jpg"),
            ("sample.tiff", "upload.tiff"),
        ],
    )
    def test_each_accepted_format_answers_with_the_text_the_page_count_the_time_and_the_model(
        self, client: TestClient, parser: FakeParser, name: str, neutral: str
    ) -> None:
        content = sample(name)

        response = post_file(client, content, name=name)

        assert response.status_code == 200
        assert response.json() == {
            "text": "# Fake page\n\nfake text",
            "page_count": 1,
            "elapsed_ms": 12,
            "model": "fake/model",
        }
        assert parser.calls == [(len(content), neutral)]

    def test_the_type_comes_from_the_bytes_not_from_the_name_or_the_content_type(
        self, client: TestClient, parser: FakeParser
    ) -> None:
        response = client.post(URL, files={"file": ("report.pdf", sample("sample.png"), "application/pdf")})

        assert response.status_code == 200
        assert parser.calls[0][1] == "upload.png"

    def test_the_default_output_is_markdown_and_text_asks_for_plain_text(self, client: TestClient) -> None:
        markdown = post_file(client, sample("sample.png"))
        plain = post_file(client, sample("sample.png"), params={"format": "text"})

        assert markdown.json()["text"] == "# Fake page\n\nfake text"
        assert plain.json()["text"] == "Fake page fake text"

    def test_the_named_format_markdown_is_accepted(self, client: TestClient) -> None:
        assert post_file(client, sample("sample.png"), params={"format": "markdown"}).status_code == 200


class TestRefusals:
    def test_an_empty_file_is_400_invalid_file(self, client: TestClient, parser: FakeParser) -> None:
        response = post_file(client, b"")

        assert response.status_code == 400
        assert response.headers["content-type"] == PROBLEM
        assert response.json()["type"] == f"{TYPE}invalid-file"
        assert parser.calls == []

    def test_a_file_the_parser_cannot_read_is_400_invalid_file(self, app: FastAPI, client: TestClient) -> None:
        app.state.parser = FakeParser(error=InvalidFile())

        response = post_file(client, sample("sample.png"))

        assert response.status_code == 400
        assert response.json()["type"] == f"{TYPE}invalid-file"

    @pytest.mark.parametrize(
        "content",
        [pytest.param(b"hello", id="text"), pytest.param(b"GIF89a....", id="gif"), pytest.param(b"<html/>", id="html")],
    )
    def test_a_type_that_is_not_accepted_is_415(self, client: TestClient, parser: FakeParser, content: bytes) -> None:
        response = client.post(URL, files={"file": ("report.pdf", content, "application/pdf")})

        assert response.status_code == 415
        assert response.json()["type"] == f"{TYPE}unsupported-media-type"
        assert parser.calls == []

    def test_a_file_over_the_limit_but_within_the_slack_is_413_from_the_service(
        self, client: TestClient, parser: FakeParser
    ) -> None:
        response = post_file(client, png_of_size(BYTES_PER_MB + 1))

        assert response.status_code == 413
        assert response.headers["content-type"] == PROBLEM
        assert response.json()["type"] == f"{TYPE}file-too-large"
        assert "1 MB" in response.json()["detail"]
        assert parser.calls == []

    def test_a_body_far_over_the_limit_is_413_before_it_is_read(self, client: TestClient, parser: FakeParser) -> None:
        response = post_file(client, png_of_size(3 * BYTES_PER_MB))

        assert response.status_code == 413
        assert response.json()["type"] == f"{TYPE}file-too-large"
        assert "x-request-id" in response.headers
        assert parser.calls == []

    @pytest.mark.parametrize("size", [BYTES_PER_MB + 1, 3 * BYTES_PER_MB], ids=["within-slack", "past-the-cap"])
    def test_a_chunked_body_without_content_length_is_413_too(
        self, app: FastAPI, parser: FakeParser, size: int
    ) -> None:
        seen: list[dict[bytes, bytes]] = []

        async def spy(scope: Any, receive: Any, send: Any) -> None:
            if scope["type"] == "http":
                seen.append(dict(scope["headers"]))
            await app(scope, receive, send)

        client = TestClient(spy)  # no lifespan: the app has no parser loaded, so give it one
        app.state.parser = parser

        response = client.post(URL, content=multipart_chunks(png_of_size(size)), headers={"Content-Type": MULTIPART})

        assert b"content-length" not in seen[0], "the request must be chunked, or this is a Content-Length test"
        assert response.status_code == 413
        assert response.json()["type"] == f"{TYPE}file-too-large"
        assert parser.calls == []

    def test_a_chunked_body_within_the_limit_is_parsed(self, app: FastAPI, parser: FakeParser) -> None:
        app.state.parser = parser
        client = TestClient(app)

        response = client.post(URL, content=multipart_chunks(sample("sample.png")), headers={"Content-Type": MULTIPART})

        assert response.status_code == 200
        assert len(parser.calls) == 1


class TestValidation:
    def test_an_unknown_format_is_422_and_the_value_is_not_echoed(self, client: TestClient) -> None:
        response = post_file(client, sample("sample.png"), params={"format": "html-leak-marker"})

        assert response.status_code == 422
        assert response.json()["type"] == f"{TYPE}validation-error"
        assert response.json()["errors"][0]["loc"] == ["query", "format"]
        assert "html-leak-marker" not in response.text

    def test_a_request_without_a_file_is_422(self, client: TestClient) -> None:
        response = client.post(URL, data={"other": "value"}, files={"x": ("x", b"y")})

        assert response.status_code == 422
        assert response.json()["errors"][0]["loc"] == ["body", "file"]

    def test_a_file_field_that_holds_text_is_422(self, client: TestClient, parser: FakeParser) -> None:
        response = client.post(URL, data={"file": "not a file"}, files={"x": ("x", b"y")})

        assert response.status_code == 422
        assert parser.calls == []

    def test_a_repeated_format_parameter_is_422(self, client: TestClient) -> None:
        response = client.post(
            URL,
            files={"file": ("a.png", sample("sample.png"), "image/png")},
            params=[("format", "text"), ("format", "markdown")],
        )

        assert response.status_code == 422
        assert response.json()["errors"][0]["type"] == "repeated_parameter"

    def test_a_body_with_the_wrong_boundary_is_a_plain_400(self, client: TestClient, parser: FakeParser) -> None:
        body = multipart_body(sample("sample.png"))

        response = client.post(
            URL, content=body, headers={"Content-Type": "multipart/form-data; boundary=other-boundary"}
        )

        assert response.status_code == 400
        assert response.headers["content-type"] == PROBLEM
        assert response.json()["type"] == "about:blank"
        assert response.json()["detail"] == "Invalid multipart data."
        assert parser.calls == []

    def test_a_multipart_request_without_a_boundary_is_a_plain_400(self, client: TestClient) -> None:
        response = client.post(URL, content=b"x", headers={"Content-Type": "multipart/form-data"})

        assert response.status_code == 400

    def test_a_json_body_is_422_because_the_file_is_missing(self, client: TestClient) -> None:
        response = client.post(URL, json={"file": "abc"})

        assert response.status_code == 422


class TestFailures:
    def test_a_failed_parse_is_500_with_fixed_text_and_nothing_from_the_cause(
        self, app: FastAPI, client: TestClient
    ) -> None:
        failure = ParseFailed()
        failure.__cause__ = RuntimeError("cause-text-marker-7714")
        app.state.parser = FakeParser(error=failure)

        response = post_file(client, sample("sample.png"))

        assert response.status_code == 500
        assert response.headers["content-type"] == PROBLEM
        assert response.json()["type"] == f"{TYPE}parse-failed"
        assert response.json()["detail"] == "The document could not be parsed."
        assert "cause-text-marker-7714" not in response.text

    def test_a_slot_is_free_again_after_a_failed_parse(self, app: FastAPI, client: TestClient) -> None:
        failing = FakeParser(error=ParseFailed())
        app.state.parser = failing

        first = post_file(client, sample("sample.png"))
        app.state.parser = FakeParser()
        second = post_file(client, sample("sample.png"))

        assert (first.status_code, second.status_code) == (500, 200)  # MAX_CONCURRENCY is 1

    def test_a_busy_parser_is_503_with_retry_after_and_its_own_type(
        self, app: FastAPI, client: TestClient, parser: FakeParser
    ) -> None:
        with app.state.parse_slots.hold():
            response = post_file(client, sample("sample.png"))

        assert response.status_code == 503
        assert response.headers["Retry-After"] == "5"
        assert response.headers["content-type"] == PROBLEM
        assert response.json()["type"] == f"{TYPE}parser-busy"
        assert parser.calls == []

    def test_a_model_that_is_not_loaded_is_503_model_unavailable_without_retry_after(
        self, app: FastAPI, client: TestClient
    ) -> None:
        app.state.parser = None

        response = post_file(client, sample("sample.png"))

        assert response.status_code == 503
        assert response.json()["type"] == f"{TYPE}model-unavailable"
        assert "Retry-After" not in response.headers


class TestReadiness:
    def test_the_service_is_ready_once_the_model_is_loaded(self, client: TestClient) -> None:
        response = client.get("/health/ready")

        assert response.status_code == 200
        assert response.json()["checks"]["model"] == "ok"

    def test_the_service_is_not_ready_without_a_model_but_still_alive(self, app: FastAPI, client: TestClient) -> None:
        app.state.parser = None

        ready = client.get("/health/ready")

        assert ready.status_code == 503
        assert ready.json()["type"] == f"{TYPE}service-not-ready"
        assert ready.json()["detail"] == "Not ready: model"
        assert client.get("/health").status_code == 200


class TestCors:
    ORIGIN = "https://app.example.com"

    @pytest.fixture
    def cors_app(self, parser: FakeParser) -> FastAPI:
        return create_app(make_settings(max_upload_mb=1, cors_origins=[self.ORIGIN]), parser_factory=lambda _: parser)

    @pytest.fixture
    def cors_client(self, cors_app: FastAPI) -> Iterator[TestClient]:
        with TestClient(cors_app) as client:
            yield client

    def test_a_browser_may_read_retry_after(self, cors_app: FastAPI, cors_client: TestClient) -> None:
        with cors_app.state.parse_slots.hold():  # the only slot, so the parser is busy
            response = cors_client.post(
                URL, files={"file": ("a.png", sample("sample.png"), "image/png")}, headers={"Origin": self.ORIGIN}
            )

        assert response.status_code == 503
        exposed = response.headers["access-control-expose-headers"]
        assert "Retry-After" in exposed
        assert "X-Request-ID" in exposed

    def test_a_refused_body_carries_the_request_id_and_the_cors_headers(self, cors_client: TestClient) -> None:
        response = cors_client.post(
            URL, files={"file": ("a.png", png_of_size(3 * BYTES_PER_MB), "image/png")}, headers={"Origin": self.ORIGIN}
        )

        assert response.status_code == 413
        assert response.headers["access-control-allow-origin"] == self.ORIGIN
        assert response.headers["X-Request-ID"] == response.json()["request_id"]


class TestLogs:
    MARKER = "unique-marker-5f3a9c"

    def test_neither_the_text_nor_the_file_name_reaches_a_log_line(
        self, app: FastAPI, client: TestClient, capsys: pytest.CaptureFixture[str], caplog: pytest.LogCaptureFixture
    ) -> None:
        app.state.parser = FakeParser(
            ParseResult(
                text=f"# {self.MARKER}", plain_text=self.MARKER, page_count=1, elapsed_ms=3, model_id="fake/model"
            )
        )
        content = sample("sample.png") + self.MARKER.encode()
        caplog.set_level("DEBUG")

        ok = client.post(URL, files={"file": (f"{self.MARKER}-patient.png", content, "image/png")})
        refused = client.post(
            URL, files={"file": (f"{self.MARKER}-patient.txt", b"x" + self.MARKER.encode(), "text/plain")}
        )

        captured = capsys.readouterr()
        everything = captured.out + captured.err + caplog.text
        assert self.MARKER in ok.text  # the text is in the answer, so the check below can fail
        assert ok.status_code == 200
        assert refused.status_code == 415
        assert '"document_parsed"' in everything
        assert self.MARKER not in everything
        assert "patient" not in everything

    def test_a_failed_parse_logs_one_error_and_the_cause_type_but_not_its_text(
        self, app: FastAPI, client: TestClient, capsys: pytest.CaptureFixture[str]
    ) -> None:
        failure = ParseFailed()
        failure.__cause__ = RuntimeError(self.MARKER)
        app.state.parser = FakeParser(error=failure)

        post_file(client, sample("sample.png"), name=f"{self.MARKER}.png")

        events = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.startswith("{")]
        parsed = [e for e in events if e["event"] == "document_parsed"]
        errors = [e for e in events if e["event"] == "request_failed"]
        assert [(e["status"], e["cause_type"], e["level"]) for e in parsed] == [("failed", "RuntimeError", "info")]
        assert len(errors) == 1  # the failure is logged as an error once, by the handler that answers it
        assert errors[0]["request_id"] == parsed[0]["request_id"]
        assert self.MARKER not in json.dumps(events)


def test_the_spec_says_the_file_part_is_not_empty_and_the_service_refuses_an_empty_one(
    app: FastAPI, client: TestClient
) -> None:
    """Schemathesis builds its valid requests from the spec: an empty file must not be one of them."""
    file_schema = app.openapi()["components"]["schemas"]["Body_parse_document"]["properties"]["file"]

    reply = post_file(client, b"")

    assert file_schema["minLength"] == 1
    assert reply.status_code == 400
