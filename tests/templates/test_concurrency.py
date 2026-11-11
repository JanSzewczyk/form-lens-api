"""Replacements that arrive at the same moment: every one gets its own version and the row holds the last."""

import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.templates.factories import field_body, template_body

THREADS = 8
URL = "/v1/templates"
# One round of a race can pass by luck: the guard test runs on fresh data in each of five rounds.
ROUNDS = [pytest.param(number, id=f"round-{number}") for number in range(5)]


@pytest.mark.concurrency
@pytest.mark.parametrize("_round", ROUNDS)
def test_parallel_replacements_get_the_versions_two_to_n_plus_one_and_the_row_holds_the_last(
    app: FastAPI, client: TestClient, _round: int
) -> None:
    created = client.post(URL, json=template_body(name="Before")).json()
    app.openapi()  # the first request builds the OpenAPI document; do not let eight threads do it together
    barrier = threading.Barrier(THREADS, timeout=5)  # a timeout fails a stuck run fast

    def replace(writer: int) -> dict[str, Any]:
        own_client = TestClient(app)  # one client per thread; no lifespan, the app is already built
        body = template_body(name=f"writer-{writer}", fields=[field_body(name=f"field_{writer}")])
        barrier.wait()
        response = own_client.put(f"{URL}/{created['id']}", json=body)
        assert response.status_code == 200, response.text
        answer: dict[str, Any] = response.json()
        return answer

    with ThreadPoolExecutor(THREADS) as pool:  # pool size >= Barrier parties
        answers = list(pool.map(replace, range(THREADS)))

    stored = client.get(f"{URL}/{created['id']}").json()
    last = max(answers, key=lambda answer: answer["version"])
    assert sorted(answer["version"] for answer in answers) == list(range(2, THREADS + 2))
    assert stored["version"] == THREADS + 1
    # The row is the content of the replacement that got the highest version, whole: no mix of two writers.
    assert (stored["name"], [item["name"] for item in stored["fields"]]) == (
        last["name"],
        [item["name"] for item in last["fields"]],
    )
    assert stored["name"].removeprefix("writer-") == stored["fields"][0]["name"].removeprefix("field_")
