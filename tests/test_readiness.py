import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from formlens.health.readiness import register_readiness_check


def broken() -> None:
    raise ConnectionError("db password is hunter2")


def test_ready_lists_only_the_model_check_when_nothing_else_is_registered(client: TestClient) -> None:
    response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "checks": {"model": "ok"}}


def test_ready_lists_each_passing_check(app: FastAPI, client: TestClient) -> None:
    register_readiness_check(app, "storage", lambda: None)

    response = client.get("/health/ready")

    assert response.json() == {"status": "ready", "checks": {"model": "ok", "storage": "ok"}}


def test_failed_check_is_a_503_problem_naming_the_check_not_the_error(
    app: FastAPI, client: TestClient, capsys: pytest.CaptureFixture[str]
) -> None:
    register_readiness_check(app, "storage", lambda: None)
    register_readiness_check(app, "database", broken)

    response = client.get("/health/ready")

    body = response.json()
    assert response.status_code == 503
    assert response.headers["content-type"] == "application/problem+json"
    assert body["type"] == "urn:problem:formlens:service-not-ready"
    assert body["detail"] == "Not ready: database"
    assert "hunter2" not in response.text
    logged = [json.loads(line) for line in capsys.readouterr().out.splitlines() if "readiness_check" in line]
    assert logged[0]["check"] == "database"


def test_liveness_ignores_failing_checks(app: FastAPI, client: TestClient) -> None:
    register_readiness_check(app, "database", broken)

    assert client.get("/health").json() == {"status": "ok"}
