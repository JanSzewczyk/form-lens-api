"""The model client talks to the configured host and to nothing else, even when the environment names a proxy.

A mock transport opens no socket, so it proves nothing here. This test runs the real transport against a tiny
server on 127.0.0.1 and records every connect the process makes. The proxy variables point at a host that
would take the documents if the client read them; `trust_env=False` is what keeps it away.
"""

import json
import socket
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import httpx2
import pytest

from formlens.extractions.adapters.ollama_extractor import OllamaFieldExtractor
from formlens.extractions.domain.exceptions import LlmUnavailable
from tests.extractions.factories import TemplateSnapshotFactory

PROXY_HOST = "10.255.255.1"
ANSWER = json.dumps({"choices": [{"message": {"content": json.dumps({"number": "INV-42", "buyer": None})}}]})


class Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        self.rfile.read(int(self.headers.get("Content-Length", "0")))
        body = ANSWER.encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002  # the signature of the base class
        """Say nothing."""


@pytest.fixture
def server() -> Iterator[int]:
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield int(httpd.server_address[1])
    httpd.shutdown()
    httpd.server_close()
    thread.join(5)


@pytest.fixture
def connects(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, int]]:
    """Record every address a connect goes to; let the stub through and refuse every other address."""
    seen: list[tuple[str, int]] = []
    real_create = socket.create_connection
    real_connect = socket.socket.connect

    def address_of(target: Any) -> tuple[str, int]:
        return (str(target[0]), int(target[1]))

    def create_connection(address: Any, *args: Any, **kwargs: Any) -> Any:
        seen.append(address_of(address))
        if seen[-1][0] != "127.0.0.1":
            raise OSError("blocked by the test")
        return real_create(address, *args, **kwargs)

    def connect(self: socket.socket, address: Any) -> None:
        seen.append(address_of(address))
        if seen[-1][0] != "127.0.0.1":
            raise OSError("blocked by the test")
        real_connect(self, address)

    monkeypatch.setattr(socket, "create_connection", create_connection)
    monkeypatch.setattr(socket.socket, "connect", connect)
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        monkeypatch.setenv(name, f"http://{PROXY_HOST}:3128")
    monkeypatch.delenv("NO_PROXY", raising=False)
    monkeypatch.delenv("no_proxy", raising=False)
    return seen


def test_an_extraction_contacts_only_the_configured_host_even_with_a_proxy_in_the_environment(
    server: int, connects: list[tuple[str, int]]
) -> None:
    client = OllamaFieldExtractor(base_url=f"http://127.0.0.1:{server}/v1", model="m", timeout_seconds=5)
    try:
        result = client.extract("text", TemplateSnapshotFactory.build())
    finally:
        client.close()

    assert result == {"number": "INV-42", "buyer": None}
    assert connects
    assert set(connects) == {("127.0.0.1", server)}


def test_the_guard_sees_the_proxy_when_the_client_is_allowed_to_read_the_environment(
    server: int, connects: list[tuple[str, int]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The test above is worth something only if it goes red when `trust_env` is on."""
    real_client = httpx2.Client
    monkeypatch.setattr(httpx2, "Client", lambda **kwargs: real_client(**{**kwargs, "trust_env": True}))
    client = OllamaFieldExtractor(base_url=f"http://127.0.0.1:{server}/v1", model="m", timeout_seconds=5)
    try:
        with pytest.raises(LlmUnavailable):
            client.extract("text", TemplateSnapshotFactory.build())
    finally:
        client.close()

    assert (PROXY_HOST, 3128) in connects
