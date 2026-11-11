"""The real adapter with the real model, through the app: `make test-models` runs these.

The model repeats lines on some samples, so the tests check that a word of the document is in the text
and that the text is not empty, never that it equals the document.
"""

import os
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from formlens.main import create_app
from formlens.migrations import upgrade_to_head
from formlens.modelspec import MODEL_SPECS
from tests.conftest import slow_settings
from tests.documents import sample

pytestmark = [pytest.mark.slow, pytest.mark.timeout(600)]


@pytest.fixture(scope="module")
def real_client(tmp_path_factory: pytest.TempPathFactory) -> Iterator[TestClient]:
    """One app with the real model loaded at startup: loading takes seconds and no test changes it."""
    offline = os.environ.get("HF_HUB_OFFLINE")  # the adapter sets it in this process; put it back afterwards
    url = f"sqlite:///{tmp_path_factory.mktemp('real') / 'formlens.db'}"
    upgrade_to_head(url)  # the start checks that the database is at the newest revision
    settings = slow_settings().model_copy(update={"db_url": url})
    with TestClient(create_app(settings, start_worker=False)) as client:
        yield client
    if offline is None:
        os.environ.pop("HF_HUB_OFFLINE", None)
    else:
        os.environ["HF_HUB_OFFLINE"] = offline


@pytest.mark.parametrize(
    ("name", "media_type"),
    [
        pytest.param("text_layer.pdf", "application/pdf", id="pdf-with-a-text-layer"),
        pytest.param("scan.pdf", "application/pdf", id="pdf-that-is-a-scan"),
        pytest.param("sample.png", "image/png", id="png"),
    ],
)
def test_a_document_is_read_into_markdown_with_its_words_and_one_page(
    real_client: TestClient, name: str, media_type: str
) -> None:
    reply = real_client.post("/v1/documents/parse", files={"file": (name, sample(name), media_type)})

    body = reply.json()
    assert reply.status_code == 200, body
    assert "invoice" in body["text"].lower()
    assert body["page_count"] == 1
    assert body["elapsed_ms"] > 0
    assert body["model"] == MODEL_SPECS[slow_settings().vlm_backend].repo


def test_the_text_format_returns_the_words_without_markdown_headings(real_client: TestClient) -> None:
    reply = real_client.post(
        "/v1/documents/parse",
        params={"format": "text"},
        files={"file": ("sample.png", sample("sample.png"), "image/png")},
    )

    body = reply.json()
    assert reply.status_code == 200, body
    assert "invoice" in body["text"].lower()
    assert not body["text"].lstrip().startswith("#")
