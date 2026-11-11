"""POST /v1/documents/parse through the HTTP test client, with a fake parser."""

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx2 import Response

from formlens.config import Settings
from formlens.main import create_app
from formlens.parsing.docling_parser import DoclingParser
from formlens.parsing.exceptions import InvalidFile, ModelUnavailable, ParseFailed
from formlens.parsing.models import BYTES_PER_MB
from formlens.parsing.ports import ParseResult
from tests.conftest import make_settings
from tests.documents import MULTIPART, PNG_SIGNATURE, multipart_body, multipart_chunks, png_of_size, sample
from tests.extractions.fakes import FakeExtractor
from tests.fakes import FakeParser

URL = "/v1/documents/parse"
PROBLEM = "application/problem+json"
TYPE = "urn:problem:formlens:"


def post_file(
    client: TestClient, content: bytes, *, name: str = "scan.png", params: dict[str, str] | None = None
) -> Response:
    return client.post(URL, files={"file": (name, content, "application/octet-stream")}, params=params)


@pytest.fixture
def settings(db_url: str) -> Settings:
    return make_settings(max_upload_mb=1, db_url=db_url)


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
    def cors_app(self, parser: FakeParser, db_url: str) -> FastAPI:
        return create_app(
            make_settings(max_upload_mb=1, cors_origins=[self.ORIGIN], db_url=db_url),
            parser_factory=lambda _: parser,
            extractor_factory=lambda _: FakeExtractor(),
            start_worker=False,
        )

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


class TestSizeLimit:
    def test_a_file_of_exactly_the_limit_is_parsed(self, client: TestClient, parser: FakeParser) -> None:
        response = post_file(client, png_of_size(BYTES_PER_MB))

        assert response.status_code == 200
        assert parser.calls == [(BYTES_PER_MB, "upload.png")]

    def test_a_chunked_body_with_a_file_of_exactly_the_limit_is_parsed(self, app: FastAPI, parser: FakeParser) -> None:
        app.state.parser = parser
        client = TestClient(app)

        response = client.post(
            URL, content=multipart_chunks(png_of_size(BYTES_PER_MB)), headers={"Content-Type": MULTIPART}
        )

        assert response.status_code == 200
        assert parser.calls == [(BYTES_PER_MB, "upload.png")]


class TestOrderOfChecks:
    """empty (400), then size (413), then type (415), then a free slot (503), then the parser."""

    def test_a_file_that_is_too_large_is_413_before_its_type_is_looked_at(
        self, client: TestClient, parser: FakeParser
    ) -> None:
        response = post_file(client, b"x" * (BYTES_PER_MB + 1))

        assert response.status_code == 413
        assert response.json()["type"] == f"{TYPE}file-too-large"
        assert parser.calls == []

    @pytest.mark.parametrize(
        ("content", "status", "slug"),
        [
            pytest.param(b"", 400, "invalid-file", id="empty-beats-busy"),
            pytest.param(b"x" * (BYTES_PER_MB + 1), 413, "file-too-large", id="too-large-beats-busy"),
            pytest.param(b"not a document", 415, "unsupported-media-type", id="unsupported-beats-busy"),
            pytest.param(png_of_size(100), 503, "parser-busy", id="busy-when-everything-else-is-fine"),
        ],
    )
    def test_every_refusal_of_the_upload_comes_before_the_busy_parser(
        self, app: FastAPI, client: TestClient, parser: FakeParser, content: bytes, status: int, slug: str
    ) -> None:
        with app.state.parse_slots.hold():  # the only slot is taken
            response = post_file(client, content)

        assert response.status_code == status
        assert response.json()["type"] == f"{TYPE}{slug}"
        assert parser.calls == []

    def test_a_missing_model_is_refused_before_the_upload_is_checked(self, app: FastAPI, client: TestClient) -> None:
        app.state.parser = None

        response = post_file(client, b"not a document")

        assert response.status_code == 503
        assert response.json()["type"] == f"{TYPE}model-unavailable"


class TestTypeFromTheBytes:
    PDF = b"%PDF-1.7\n%%EOF"

    @pytest.mark.parametrize(
        ("content", "name", "content_type", "neutral"),
        [
            pytest.param(PDF, "scan.png", "image/png", "upload.pdf", id="pdf-called-png"),
            pytest.param(
                PNG_HEAD := b"\x89PNG\r\n\x1a\n" + bytes(32),
                "doc.pdf",
                "application/pdf",
                "upload.png",
                id="png-called-pdf",
            ),
            pytest.param(b"MM\x00*" + bytes(32), "report.pdf", "application/pdf", "upload.tiff", id="big-endian-tiff"),
            pytest.param(b"II*\x00" + bytes(32), "report.jpg", "image/jpeg", "upload.tiff", id="little-endian-tiff"),
            pytest.param(b"\xff\xd8\xff\xe0" + bytes(32), "x.txt", "text/plain", "upload.jpg", id="jpeg-called-txt"),
            pytest.param(b"\xef\xbb\xbf" + PDF, "x.pdf", "application/pdf", "upload.pdf", id="pdf-after-a-bom"),
            pytest.param(b"x" * 500 + PDF, "x.pdf", "application/pdf", "upload.pdf", id="pdf-header-after-500-bytes"),
        ],
    )
    def test_the_neutral_name_follows_the_bytes_whatever_the_client_says(
        self, client: TestClient, parser: FakeParser, content: bytes, name: str, content_type: str, neutral: str
    ) -> None:
        response = client.post(URL, files={"file": (name, content, content_type)})

        assert response.status_code == 200
        assert parser.calls == [(len(content), neutral)]

    @pytest.mark.parametrize(
        "content",
        [
            pytest.param(b" \n\t ", id="whitespace-only"),
            pytest.param(b"\x00", id="one-null-byte"),
            pytest.param(b"\x89PNG\r\n\x1a", id="png-signature-one-byte-short"),
            pytest.param(b"\xff\xd8", id="jpeg-signature-one-byte-short"),
            pytest.param(b"II*", id="tiff-signature-one-byte-short"),
            pytest.param(b"%PDF", id="pdf-marker-without-the-dash"),
            pytest.param(b"x" * 1100 + b"%PDF-1.7", id="pdf-header-far-past-the-first-kilobyte"),
            pytest.param(b"PK\x03\x04" + bytes(32), id="zip"),
        ],
    )
    def test_anything_without_a_known_signature_is_415_even_with_a_pdf_name_and_type(
        self, client: TestClient, parser: FakeParser, content: bytes
    ) -> None:
        response = client.post(URL, files={"file": ("invoice.pdf", content, "application/pdf")})

        assert response.status_code == 415
        assert response.json()["type"] == f"{TYPE}unsupported-media-type"
        assert parser.calls == []

    def test_a_png_that_mentions_a_pdf_in_its_first_kilobyte_is_still_a_png(
        self, client: TestClient, parser: FakeParser
    ) -> None:
        """A metadata chunk can hold any text; the signature at offset 0 is what types the file."""
        content = PNG_SIGNATURE + b"\x00\x00\x00\x20tEXtSoftware\x00converted from %PDF-1.4" + bytes(64)

        response = post_file(client, content)

        assert response.status_code == 200
        assert parser.calls == [(len(content), "upload.png")]


class TestFileNames:
    @pytest.mark.parametrize(
        "name",
        [
            pytest.param("../../../etc/passwd", id="path-traversal"),
            pytest.param("..\\..\\windows\\system32\\config.png", id="windows-traversal"),
            pytest.param("/absolute/path/scan.png", id="absolute-path"),
            pytest.param("zażółć-文書-🙂.png", id="unicode"),
            pytest.param("a" * 251 + ".png", id="255-characters"),
            pytest.param('quote".png', id="quote"),
            pytest.param("scan.pdf.exe", id="double-extension"),
            pytest.param("%00.png", id="encoded-null"),
        ],
    )
    def test_the_parser_gets_a_neutral_name_and_never_the_clients(
        self, client: TestClient, parser: FakeParser, name: str
    ) -> None:
        response = client.post(URL, files={"file": (name, sample("sample.png"), "image/png")})

        assert response.status_code == 200
        assert [call[1] for call in parser.calls] == ["upload.png"]

    @pytest.mark.parametrize(
        "filename",
        [pytest.param("", id="empty-name")],
    )
    def test_a_part_with_an_empty_file_name_is_still_the_file_because_the_name_is_ignored(
        self, client: TestClient, parser: FakeParser, filename: str
    ) -> None:
        disposition = f'form-data; name="file"; filename="{filename}"'
        body = (
            f"--B\r\nContent-Disposition: {disposition}\r\nContent-Type: image/png\r\n\r\n".encode()
            + sample("sample.png")
            + b"\r\n--B--\r\n"
        )

        response = client.post(URL, content=body, headers={"Content-Type": "multipart/form-data; boundary=B"})

        assert response.status_code == 200
        assert [call[1] for call in parser.calls] == ["upload.png"]

    def test_a_part_without_a_file_name_is_refused_with_422_not_read_as_text(
        self, client: TestClient, parser: FakeParser
    ) -> None:
        """RFC 7578 makes `filename` optional, but Starlette reads a part without one as a text field: it caps
        it at 1 MB and decodes it as text, which would corrupt the bytes of a document. A clean 422 is the
        contract; supporting this would need a multipart parser of our own."""
        body = (
            b'--B\r\nContent-Disposition: form-data; name="file"\r\nContent-Type: image/png\r\n\r\n'
            + sample("sample.png")
            + b"\r\n--B--\r\n"
        )

        response = client.post(URL, content=body, headers={"Content-Type": "multipart/form-data; boundary=B"})

        assert response.status_code == 422
        assert response.json()["errors"][0]["loc"] == ["body", "file"]
        assert parser.calls == []


class TestFormShape:
    def test_other_form_fields_and_query_parameters_are_ignored(self, client: TestClient, parser: FakeParser) -> None:
        response = client.post(
            URL,
            data={"comment": "hello", "format": "text"},
            files={"file": ("a.png", sample("sample.png"), "image/png")},
            params={"unrelated": "1"},
        )

        assert response.status_code == 200
        assert response.json()["text"] == "# Fake page\n\nfake text"  # `format` is a query parameter only
        assert len(parser.calls) == 1

    @pytest.mark.parametrize("value", ["Markdown", "TEXT", "", " text", "text ", "json", "html", "md"])
    def test_a_format_that_is_not_exactly_markdown_or_text_is_422(
        self, client: TestClient, parser: FakeParser, value: str
    ) -> None:
        response = post_file(client, sample("sample.png"), params={"format": value})

        assert response.status_code == 422
        assert response.json()["errors"][0]["loc"] == ["query", "format"]
        assert parser.calls == []

    def test_two_files_in_one_request_are_refused_and_neither_is_parsed(
        self, client: TestClient, parser: FakeParser
    ) -> None:
        """Starlette keeps the last `file` part and drops the others without a word; the request is refused."""
        response = client.post(
            URL,
            files=[
                ("file", ("first.png", sample("sample.png"), "image/png")),
                ("file", ("second.png", sample("sample.png"), "image/png")),
            ],
        )

        assert response.status_code == 422
        assert response.json()["errors"][0]["type"] == "repeated_parameter"
        assert response.json()["errors"][0]["loc"] == ["body", "file"]
        assert parser.calls == []

    @pytest.mark.parametrize("content_type", ["application/json", "text/plain", "application/x-www-form-urlencoded"])
    def test_a_body_that_is_not_multipart_is_422_because_the_file_is_missing(
        self, client: TestClient, parser: FakeParser, content_type: str
    ) -> None:
        response = client.post(URL, content=sample("sample.png"), headers={"Content-Type": content_type})

        assert response.status_code == 422
        assert response.json()["errors"][0]["loc"] == ["body", "file"]
        assert parser.calls == []

    def test_an_empty_body_is_422(self, client: TestClient) -> None:
        response = client.post(URL)

        assert response.status_code == 422


class TestParserMisbehaviour:
    def test_a_parser_that_says_the_model_is_gone_is_503_model_unavailable_and_gives_its_slot_back(
        self, app: FastAPI, client: TestClient
    ) -> None:
        app.state.parser = FakeParser(error=ModelUnavailable())

        first = post_file(client, sample("sample.png"))
        second = post_file(client, sample("sample.png"))

        assert (first.status_code, second.status_code) == (503, 503)
        assert first.json()["type"] == f"{TYPE}model-unavailable"
        assert "Retry-After" not in first.headers

    @pytest.mark.parametrize(
        "result",
        [
            pytest.param(ParseResult("t", "t", -1, 1, "m"), id="negative-page-count"),
            pytest.param(ParseResult("t", "t", 1, -1, "m"), id="negative-time"),
        ],
    )
    def test_a_result_the_response_model_cannot_carry_is_a_500_with_nothing_of_it_and_the_slot_is_free(
        self, app: FastAPI, result: ParseResult
    ) -> None:
        app.state.parser = FakeParser(result)
        client = TestClient(app, raise_server_exceptions=False)

        first = post_file(client, sample("sample.png"))
        app.state.parser = FakeParser()
        second = post_file(client, sample("sample.png"))

        assert (first.status_code, second.status_code) == (500, 200)  # MAX_CONCURRENCY is 1
        assert first.headers["content-type"] == PROBLEM
        assert "X-Request-ID" in first.headers

    def test_a_parser_that_raises_an_unexpected_error_leaves_its_text_out_of_the_logs(
        self, app: FastAPI, capsys: pytest.CaptureFixture[str], caplog: pytest.LogCaptureFixture
    ) -> None:
        """The port says an adapter wraps every failure; a library error can still quote the document."""
        app.state.parser = FakeParser(error=ValueError("cannot read: unique-marker-8d21"))
        client = TestClient(app, raise_server_exceptions=False)
        caplog.set_level("DEBUG")

        response = post_file(client, sample("sample.png"))

        captured = capsys.readouterr()
        everything = captured.out + captured.err + caplog.text
        assert response.status_code == 500
        assert "unique-marker-8d21" not in response.text
        assert '"request_completed"' in everything
        assert "unique-marker-8d21" not in everything


class TestLogsAtDebug:
    """The service logs the request id, the size, the page count, the time and the status, and nothing else."""

    MARKER = "unique-marker-c07e1b"

    @pytest.fixture
    def settings(self, db_url: str) -> Settings:
        return make_settings(max_upload_mb=1, log_level="DEBUG", db_url=db_url)

    @pytest.mark.parametrize(
        ("content", "status"),
        [
            pytest.param(sample("sample.png") + MARKER.encode(), 200, id="parsed"),
            pytest.param(b"not a document " + MARKER.encode(), 415, id="unsupported"),
            pytest.param(b"", 400, id="empty"),
            pytest.param(png_of_size(BYTES_PER_MB + 1), 413, id="too-large"),
            pytest.param(png_of_size(3 * BYTES_PER_MB), 413, id="refused-by-the-body-cap"),
        ],
    )
    def test_the_file_name_never_reaches_a_log_line(
        self,
        client: TestClient,
        capsys: pytest.CaptureFixture[str],
        caplog: pytest.LogCaptureFixture,
        content: bytes,
        status: int,
    ) -> None:
        caplog.set_level("DEBUG")
        name = f"../../{self.MARKER}-jan-kowalski-diagnosis-ścieżka.png"

        response = client.post(URL, files={"file": (name, content, f"image/{self.MARKER}")})

        captured = capsys.readouterr()
        everything = captured.out + captured.err + caplog.text
        assert response.status_code == status
        assert '"request_completed"' in everything
        assert self.MARKER not in everything
        assert "kowalski" not in everything
        assert "ścieżka" not in everything

    def test_a_failure_of_the_real_adapter_leaves_the_cause_and_the_name_out_of_the_answer_and_the_logs(
        self, app: FastAPI, capsys: pytest.CaptureFixture[str], caplog: pytest.LogCaptureFixture
    ) -> None:
        class ExplodingConverter:
            def convert(self, source: Path, *, raises_on_error: bool, max_file_size: int) -> Any:
                msg = f"cannot read {source.read_bytes()[-20:]!r} {self.__class__.__name__}"
                raise RuntimeError(msg)

        app.state.parser = DoclingParser(ExplodingConverter(), model_id="m", max_file_size=BYTES_PER_MB)
        caplog.set_level("DEBUG")
        client = TestClient(app, raise_server_exceptions=False)
        content = sample("sample.png") + self.MARKER.encode()

        response = client.post(URL, files={"file": (f"{self.MARKER}.png", content, "image/png")})

        captured = capsys.readouterr()
        everything = captured.out + captured.err + caplog.text
        assert response.status_code == 500
        assert response.json()["type"] == f"{TYPE}parse-failed"
        assert '"document_parsed"' in everything
        assert self.MARKER not in everything
        assert self.MARKER not in response.text

    def test_the_one_document_line_carries_the_request_id_the_client_sent(
        self, client: TestClient, capsys: pytest.CaptureFixture[str]
    ) -> None:
        response = client.post(
            URL, files={"file": ("a.png", sample("sample.png"), "image/png")}, headers={"X-Request-ID": "trace-77"}
        )

        events = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.startswith("{")]
        [parsed] = [e for e in events if e["event"] == "document_parsed"]
        assert response.status_code == 200
        assert parsed["request_id"] == "trace-77"
        assert set(parsed) == {
            "event",
            "request_id",
            "level",
            "logger",
            "timestamp",
            "file_size_bytes",
            "page_count",
            "elapsed_ms",
            "status",
        }


class TestMalformedMultipartLogs:
    MARKER = "unique-marker-b6d4"

    @pytest.fixture
    def settings(self, db_url: str) -> Settings:
        return make_settings(max_upload_mb=1, log_level="DEBUG", db_url=db_url)

    @pytest.mark.parametrize(
        "body",
        [
            pytest.param(b"--B\r\n\x89" + MARKER.encode() * 4, id="byte-where-the-boundary-ends"),
            pytest.param(b"--BX" + MARKER.encode() + b"\r\n--B--\r\n", id="wrong-character-in-the-boundary"),
            pytest.param(b"--B\r\nContent-Disp\x80sition: x\r\n\r\n" + MARKER.encode(), id="bad-header-byte"),
        ],
    )
    def test_a_body_that_cannot_be_framed_leaks_none_of_its_bytes_to_a_log_line(
        self, client: TestClient, capsys: pytest.CaptureFixture[str], caplog: pytest.LogCaptureFixture, body: bytes
    ) -> None:
        caplog.set_level("DEBUG")

        response = client.post(URL, content=body, headers={"Content-Type": "multipart/form-data; boundary=B"})

        captured = capsys.readouterr()
        everything = captured.out + captured.err + caplog.text
        assert response.status_code in {400, 422}
        assert '"request_completed"' in everything
        assert self.MARKER not in everything
        assert not [r for r in caplog.records if r.name.startswith(("python_multipart", "multipart"))]
