"""The factory `make schemathesis` starts: a real app around a fake parser, built from the environment."""

import pytest
from fastapi.testclient import TestClient

from tests.documents import sample
from tests.schemathesis_app import create_schemathesis_app


def test_the_fuzzed_app_parses_a_document_with_the_fake_parser_and_loads_no_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ENVIRONMENT", "test")

    with TestClient(create_schemathesis_app()) as client:
        reply = client.post("/v1/documents/parse", files={"file": ("a.png", sample("sample.png"), "image/png")})
        ready = client.get("/health/ready")

    assert reply.status_code == 200
    assert reply.json()["model"] == "fake/model"
    assert ready.status_code == 200


def test_the_fuzzed_app_reads_its_settings_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("DOCS_ENABLED", "true")

    with TestClient(create_schemathesis_app()) as client:
        assert client.get("/openapi.json").status_code == 200
