"""A query parameter that takes one value is given once; a list parameter may repeat."""

import pytest
from fastapi.testclient import TestClient

from fastapi_szumplate.query import REPEATED_PARAMETER

PROBLEM = "application/problem+json"
SECRET = "s3cr3t-hunter2"


def test_a_scalar_parameter_given_twice_is_a_422_that_names_it(probe: TestClient) -> None:
    response = probe.get("/probe/limit?limit=1&limit=2")

    body = response.json()
    assert response.status_code == 422
    assert response.headers["content-type"] == PROBLEM
    assert [issue["loc"] for issue in body["errors"]] == [["query", "limit"]]
    assert body["errors"][0]["type"] == REPEATED_PARAMETER


@pytest.mark.parametrize("query", ["limit=1&limit=2", "limit=2&limit=1", f"limit=1&limit={SECRET}"], ids=str)
def test_the_order_of_the_values_does_not_matter_and_they_are_never_echoed(probe: TestClient, query: str) -> None:
    """Without the check the last value wins, so the same request would mean two things."""
    response = probe.get(f"/probe/limit?{query}")

    assert response.status_code == 422
    assert SECRET not in response.text
    assert response.json()["errors"][0]["type"] == REPEATED_PARAMETER


def test_every_repeated_scalar_parameter_is_reported_once_each(probe: TestClient) -> None:
    response = probe.get("/probe/tags?colour=red&colour=blue&tag=a&tag=b")

    assert response.status_code == 422
    assert [issue["loc"] for issue in response.json()["errors"]] == [["query", "colour"]]


def test_a_list_parameter_may_repeat(probe: TestClient) -> None:
    response = probe.get("/probe/tags?tag=a&tag=b&colour=red")

    assert response.status_code == 200
    assert response.json() == {"tag": ["a", "b"], "colour": "red"}


@pytest.mark.parametrize("path", ["/probe/limit?limit=7", "/probe/tags", "/probe/thing"])
def test_a_parameter_given_once_or_not_at_all_is_not_affected(probe: TestClient, path: str) -> None:
    assert probe.get(path).status_code == 200


def test_a_parameter_the_route_does_not_declare_is_ignored_even_when_repeated(
    probe: TestClient,
) -> None:
    assert probe.get("/probe/thing?x=1&x=2").status_code == 200


def test_a_path_that_matches_no_route_is_still_a_plain_404(probe: TestClient) -> None:
    assert probe.get("/no/such/path?a=1&a=2").status_code == 404
