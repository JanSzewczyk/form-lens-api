import json
import logging
from collections.abc import Iterator, Mapping
from typing import Any, Literal
from unittest.mock import patch

import pytest
import structlog
import uvicorn
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient
from starlette.datastructures import Headers

from formlens import __main__ as entry_point
from formlens.logging_config import _HANDLER_TAG, configure_logging
from formlens.main import create_app
from tests.conftest import make_settings


def lines(capsys: pytest.CaptureFixture[str]) -> list[dict[str, Any]]:
    out = capsys.readouterr().out
    parsed = [json.loads(line) for line in out.splitlines() if line.startswith("{")]
    return [line for line in parsed if not line["logger"].startswith("httpx")]  # test client noise


@pytest.fixture
def json_app() -> FastAPI:
    return create_app(make_settings(log_format="json"))


def test_json_line_has_the_fixed_fields(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(make_settings(log_format="json"))

    structlog.get_logger("probe").info("order_processed", order_id=7)

    [line] = lines(capsys)
    assert line["event"] == "order_processed"
    assert line["order_id"] == 7
    assert line["level"] == "info"
    assert line["logger"] == "probe"
    assert line["timestamp"].endswith("Z")


def test_console_format_is_readable(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(make_settings(log_format="console"))

    structlog.get_logger("probe").info("order_processed", order_id=7)

    out = capsys.readouterr().out
    assert "order_processed" in out
    assert not out.lstrip().startswith("{")


def test_sensitive_keys_are_masked_also_when_nested(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(make_settings(log_format="json"))

    structlog.get_logger("probe").info(
        "login", password="hunter2", headers={"Authorization": "Bearer abc", "accept": "*/*"}
    )

    [line] = lines(capsys)
    assert line["password"] == "***"
    assert line["headers"] == {"Authorization": "***", "accept": "*/*"}


def test_read_only_mappings_and_mappings_inside_sequences_are_masked(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(make_settings(log_format="json"))

    structlog.get_logger("probe").info(
        "inbound",
        headers=Headers({"authorization": "Bearer abc", "accept": "*/*"}),
        attempts=[{"token": "abc", "status": 401}],
    )

    [line] = lines(capsys)
    assert line["headers"] == {"authorization": "***", "accept": "*/*"}
    assert line["attempts"] == [{"token": "***", "status": 401}]


def test_configure_logging_is_idempotent() -> None:
    settings = make_settings(log_format="json")

    configure_logging(settings)
    configure_logging(settings)

    tagged = [h for h in logging.getLogger().handlers if getattr(h, _HANDLER_TAG, False)]
    assert len(tagged) == 1


def test_stdlib_records_share_the_pipeline(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(make_settings(log_format="json"))

    logging.getLogger("uvicorn.error").warning("worker %s restarted", 3)

    [line] = lines(capsys)
    assert line["event"] == "worker 3 restarted"
    assert line["logger"] == "uvicorn.error"
    assert line["level"] == "warning"


def test_stdlib_records_keep_their_extras_masked_and_without_uvicorns_duplicate(
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_logging(make_settings(log_format="json"))

    logging.getLogger("some.dependency").info(
        "connected", extra={"pool_size": 5, "api_token": "abc", "color_message": "\x1b[1mconnected\x1b[0m"}
    )

    [line] = lines(capsys)
    assert line["pool_size"] == 5
    assert line["api_token"] == "***"
    assert "color_message" not in line


@pytest.mark.parametrize(
    "key",
    ["filename", "file_name", "content", "markdown", "plain_text", "extracted_text", "Content", "upload_filename"],
)
def test_keys_that_could_hold_a_document_or_its_name_are_masked(capsys: pytest.CaptureFixture[str], key: str) -> None:
    configure_logging(make_settings(log_format="json"))

    structlog.get_logger("probe").info("parsed", **{key: "secret-marker-9137", "page_count": 2})

    [line] = lines(capsys)
    assert line[key] == "***"
    assert line["page_count"] == 2
    assert "secret-marker-9137" not in json.dumps(line)


def test_bare_text_is_not_masked_so_that_context_stays_readable(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(make_settings(log_format="json"))

    structlog.get_logger("probe").info("parsed", text="kept", context="kept too")

    [line] = lines(capsys)
    assert (line["text"], line["context"]) == ("kept", "kept too")


def test_content_also_masks_the_content_headers_and_nothing_else_of_a_mapping(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The cost of the `content` part: `content-type` and `content_length` are masked too (a known trade)."""
    configure_logging(make_settings(log_format="json"))

    structlog.get_logger("probe").info(
        "inbound", headers={"content-type": "application/pdf", "content_length": 12, "accept": "*/*"}
    )

    [line] = lines(capsys)
    assert line["headers"] == {"content-type": "***", "content_length": "***", "accept": "*/*"}


QUIET_LOGGERS = ["docling", "docling_core", "docling_parse", "docling_ibm_models", "transformers", "huggingface_hub"]


@pytest.fixture
def restore_logger_levels() -> Iterator[None]:
    """`configure_logging` sets levels on global loggers; put them back so no other test sees them."""
    names = [*QUIET_LOGGERS, "PIL", "mlx", "mlx_vlm", "python_multipart", "multipart", "unrelated"]
    saved = {name: logging.getLogger(name).level for name in names}
    yield
    for name, level in saved.items():
        logging.getLogger(name).setLevel(level)


@pytest.mark.parametrize("name", [*QUIET_LOGGERS, "PIL.PngImagePlugin", "mlx_vlm.utils", "transformers.modeling_utils"])
def test_the_document_stack_logs_at_info_never_reach_the_output(
    restore_logger_levels: None, capsys: pytest.CaptureFixture[str], name: str
) -> None:
    configure_logging(make_settings(log_format="json", log_level="DEBUG"))

    logging.getLogger(name).info("loading %s", "upload.pdf")
    logging.getLogger(name).warning("careful")

    [line] = lines(capsys)
    assert (line["event"], line["logger"]) == ("careful", name)


def test_the_pin_never_lets_a_library_log_below_the_configured_level(
    restore_logger_levels: None, capsys: pytest.CaptureFixture[str]
) -> None:
    """A logger set to WARNING would still write a WARNING when LOG_LEVEL is ERROR: the root level is not consulted."""
    configure_logging(make_settings(log_format="json", log_level="ERROR"))

    logging.getLogger("docling").warning("hidden")
    logging.getLogger("docling").error("shown")

    [line] = lines(capsys)
    assert line["event"] == "shown"


def test_a_logger_the_pin_does_not_name_still_follows_the_root_level(
    restore_logger_levels: None, capsys: pytest.CaptureFixture[str]
) -> None:
    configure_logging(make_settings(log_format="json", log_level="DEBUG"))

    logging.getLogger("unrelated").debug("still visible")

    [line] = lines(capsys)
    assert line["event"] == "still visible"


class _CountingMapping(Mapping[str, str]):
    """A mapping that counts how often a processor walks it."""

    def __init__(self) -> None:
        self.walks = 0

    def __getitem__(self, key: str) -> str:
        raise KeyError(key)

    def __iter__(self) -> Iterator[str]:
        self.walks += 1
        return iter(())

    def __len__(self) -> int:
        return 0


def test_a_record_below_the_level_is_dropped_before_the_processors_run() -> None:
    configure_logging(make_settings(log_format="json", log_level="WARNING"))
    payload = _CountingMapping()

    structlog.get_logger("probe").info("too_quiet", payload=payload)
    structlog.get_logger("probe").warning("loud_enough", payload=payload)

    assert payload.walks == 1


def test_log_level_filters_records(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(make_settings(log_format="json", log_level="WARNING"))

    structlog.get_logger("probe").info("too_quiet")

    assert lines(capsys) == []


def test_request_is_logged_once_with_the_route_template(json_app: FastAPI, capsys: pytest.CaptureFixture[str]) -> None:
    @json_app.get("/things/{thing_id}", operation_id="get_thing_probe")
    def get_thing(thing_id: int) -> dict[str, int]:
        return {"id": thing_id}

    response = TestClient(json_app).get("/things/42", headers={"X-Request-ID": "abc-123"})

    [line] = lines(capsys)
    assert response.headers["X-Request-ID"] == "abc-123"
    assert line["event"] == "request_completed"
    assert line["request_id"] == "abc-123"
    assert (line["method"], line["route"], line["status"]) == ("GET", "/things/{thing_id}", 200)
    assert line["duration_ms"] >= 0


@pytest.mark.parametrize(
    "inbound",
    ["has space", "x" * 65, "back\\slash", "semi;colon"],
    ids=["space", "too-long", "backslash", "separator"],
)
def test_unsafe_inbound_request_id_is_replaced(
    json_app: FastAPI, capsys: pytest.CaptureFixture[str], inbound: str
) -> None:
    response = TestClient(json_app).get("/health", headers={"X-Request-ID": inbound})

    [line] = lines(capsys)
    assert response.headers["X-Request-ID"] != inbound
    assert line["request_id"] == response.headers["X-Request-ID"]


def test_missing_request_id_is_generated_per_request(json_app: FastAPI) -> None:
    client = TestClient(json_app)

    first = client.get("/health").headers["X-Request-ID"]
    second = client.get("/health").headers["X-Request-ID"]

    assert first != second


def test_log_lines_written_by_a_handler_carry_the_request_id(
    json_app: FastAPI, capsys: pytest.CaptureFixture[str]
) -> None:
    @json_app.get("/noisy", operation_id="get_noisy_probe")
    def noisy() -> dict[str, str]:
        structlog.get_logger("probe").info("inside_handler")
        return {}

    response = TestClient(json_app).get("/noisy")

    inside, completed = lines(capsys)
    assert inside["request_id"] == completed["request_id"] == response.headers["X-Request-ID"]


def test_unmatched_path_is_logged_without_the_raw_path(json_app: FastAPI, capsys: pytest.CaptureFixture[str]) -> None:
    TestClient(json_app).get("/nope/123")

    [line] = lines(capsys)
    assert (line["route"], line["status"]) == ("unmatched", 404)


def test_unhandled_error_is_logged_as_status_500(json_app: FastAPI, capsys: pytest.CaptureFixture[str]) -> None:
    @json_app.get("/boom", operation_id="get_boom_probe")
    def boom() -> None:
        raise RuntimeError("secret internals")

    response = TestClient(json_app, raise_server_exceptions=False).get("/boom")

    [line] = lines(capsys)
    assert response.status_code == 500
    assert (line["event"], line["status"], line["level"]) == ("request_completed", 500, "error")


def test_the_traceback_of_an_unhandled_error_is_logged_once_on_the_request_line(
    json_app: FastAPI, capsys: pytest.CaptureFixture[str]
) -> None:
    @json_app.get("/boom", operation_id="get_boom_traceback_probe")
    def boom() -> None:
        raise RuntimeError("secret internals")

    TestClient(json_app, raise_server_exceptions=False).get("/boom")

    [line] = lines(capsys)
    [exception] = line["exception"]
    assert (exception["exc_type"], exception["exc_value"]) == ("RuntimeError", "secret internals")


def test_a_failure_after_the_response_started_is_logged_at_error_without_a_second_traceback(
    json_app: FastAPI, capsys: pytest.CaptureFixture[str]
) -> None:
    """Status 200 is already sent; the server logs the traceback, this line flags the request."""

    @json_app.get("/stream", operation_id="get_stream_probe")
    def stream() -> StreamingResponse:
        def chunks() -> Iterator[bytes]:
            yield b"first chunk"
            raise RuntimeError("secret internals")

        return StreamingResponse(chunks())

    with pytest.raises(RuntimeError, match="secret internals"):
        TestClient(json_app).get("/stream")

    [line] = lines(capsys)
    assert (line["event"], line["status"], line["level"]) == ("request_completed", 200, "error")
    assert line["aborted_by"] == "RuntimeError"
    assert "exception" not in line
    assert "secret internals" not in json.dumps(line)


def test_a_request_that_finishes_normally_has_no_aborted_by_field(
    json_app: FastAPI, capsys: pytest.CaptureFixture[str]
) -> None:
    TestClient(json_app).get("/health")

    [line] = lines(capsys)
    assert (line["status"], line["level"]) == (200, "info")
    assert "aborted_by" not in line


@pytest.mark.parametrize("log_format", ["json", "console"])
def test_a_logged_traceback_keeps_the_frames_but_not_the_local_variables(
    log_format: Literal["json", "console"], capsys: pytest.CaptureFixture[str]
) -> None:
    configure_logging(make_settings(log_format=log_format))

    def handle_request() -> None:
        headers = {"Authorization": "Bearer sekret-token-1"}  # a local, as ASGI's `scope` is
        raise RuntimeError(f"failed with {len(headers)} header")

    try:
        handle_request()
    except RuntimeError:
        structlog.get_logger("probe").exception("job_failed")

    out = capsys.readouterr().out
    assert "sekret-token-1" not in out
    assert "handle_request" in out
    assert "RuntimeError" in out


@pytest.mark.parametrize("log_format", ["json", "console"])
def test_an_unhandled_error_does_not_log_the_request_headers(
    log_format: Literal["json", "console"], capsys: pytest.CaptureFixture[str]
) -> None:
    app = create_app(make_settings(log_format=log_format))

    @app.get("/boom", operation_id="get_boom_secret_probe")
    def boom() -> None:
        raise RuntimeError("secret internals")

    TestClient(app, raise_server_exceptions=False).get("/boom", headers={"Authorization": "Bearer sekret-token-1"})

    out = capsys.readouterr().out
    assert "sekret-token-1" not in out
    assert "RuntimeError" in out


def test_cors_is_off_without_origins_and_exposes_the_request_id_with_them() -> None:
    plain = TestClient(create_app(make_settings()))
    cors = TestClient(create_app(make_settings(cors_origins=["https://app.example.com"])))
    origin = {"Origin": "https://app.example.com"}

    assert "access-control-allow-origin" not in plain.get("/health", headers=origin).headers
    allowed = cors.get("/health", headers=origin).headers
    assert allowed["access-control-allow-origin"] == "https://app.example.com"
    assert "X-Request-ID" in allowed["access-control-expose-headers"]
    assert "access-control-allow-credentials" not in allowed


def test_entry_point_starts_uvicorn_with_our_logging(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PORT", "9100")
    with patch.object(uvicorn, "run", autospec=True) as run:
        entry_point.main()

    run.assert_called_once()
    assert run.call_args.args == ("formlens.main:create_app",)
    kwargs = run.call_args.kwargs
    assert kwargs["factory"] is True
    assert kwargs["port"] == 9100
    assert kwargs["log_config"] is None
    assert kwargs["access_log"] is False
    assert kwargs["server_header"] is False
    assert kwargs["timeout_graceful_shutdown"] == 20


@pytest.mark.parametrize("name", ["python_multipart", "python_multipart.multipart", "multipart"])
def test_the_multipart_parser_is_held_at_error_so_it_cannot_quote_a_body_byte(
    restore_logger_levels: None, capsys: pytest.CaptureFixture[str], name: str
) -> None:
    configure_logging(make_settings(log_format="json", log_level="DEBUG"))

    logging.getLogger(name).warning("Expected boundary character %r, got %r at index %d", 45, 137, 2)
    logging.getLogger(name).error("kept")

    [line] = lines(capsys)
    assert line["event"] == "kept"
