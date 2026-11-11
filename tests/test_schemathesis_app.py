"""The factory `make schemathesis` starts: a real app around a fake parser, built from the environment."""

import pytest
from fastapi.testclient import TestClient

from tests.documents import sample
from tests.schemathesis_app import create_schemathesis_app


def test_the_fuzzed_app_parses_a_document_with_the_fake_parser_and_loads_no_model(
    monkeypatch: pytest.MonkeyPatch, db_url: str
) -> None:
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("DB_URL", db_url)

    with TestClient(create_schemathesis_app()) as client:
        reply = client.post("/v1/documents/parse", files={"file": ("a.png", sample("sample.png"), "image/png")})
        ready = client.get("/health/ready")

    assert reply.status_code == 200
    assert reply.json()["model"] == "fake/model"
    assert ready.status_code == 200


def test_the_fuzzed_app_reads_its_settings_from_the_environment(monkeypatch: pytest.MonkeyPatch, db_url: str) -> None:
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("DB_URL", db_url)
    monkeypatch.setenv("DOCS_ENABLED", "true")

    with TestClient(create_schemathesis_app()) as client:
        assert client.get("/openapi.json").status_code == 200


def test_the_fuzzed_app_queues_an_extraction_and_leaves_it_pending(
    monkeypatch: pytest.MonkeyPatch, db_url: str
) -> None:
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("DB_URL", db_url)

    with TestClient(create_schemathesis_app()) as client:
        template = client.post("/v1/templates", json={"name": "T", "fields": [{"name": "a", "type": "text"}]}).json()
        queued = client.post(
            "/v1/extractions",
            data={"template_id": template["id"]},
            files={"file": ("a.png", sample("sample.png"), "image/png")},
        )
        read = client.get(queued.headers["Location"])

    assert queued.status_code == 202
    assert read.json()["status"] == "pending"  # no worker runs in the fuzzed app
