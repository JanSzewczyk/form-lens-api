"""The real thing: the real document model and a real Ollama, through the app. `make test-models` runs these.

They fail, they do not skip, when Ollama or the models are missing, like the other `slow` tests. They check that
the whole path works and that the answer fits the template; the accuracy is what `make evaluate` measures.
"""

import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

from formlens.extractions.adapters.ollama_extractor import OllamaFieldExtractor
from formlens.main import create_app
from formlens.migrations import upgrade_to_head
from tests.conftest import slow_settings
from tests.golden.evaluate import check_ollama, snapshot
from tests.golden.generator import generate
from tests.golden.templates import TEMPLATES, body_of

pytestmark = [pytest.mark.slow, pytest.mark.timeout(900)]


def test_ollama_is_running_and_has_the_model_of_the_settings() -> None:
    settings = slow_settings()

    check_ollama(settings.llm_base_url, settings.llm_model)  # raises with what to do when it is not


def test_the_model_answers_for_a_text_with_a_result_that_fits_the_schema() -> None:
    settings = slow_settings()
    document = generate()[0]
    extractor = OllamaFieldExtractor(
        base_url=settings.llm_base_url, model=settings.llm_model, timeout_seconds=settings.llm_timeout_seconds
    )
    try:
        result = extractor.extract("\n".join(document.lines), snapshot("zgoda", TEMPLATES["zgoda"]))
    finally:
        extractor.close()

    assert Draft202012Validator(snapshot("zgoda", TEMPLATES["zgoda"]).json_schema).is_valid(result)
    assert any(value is not None for value in result.values())


def test_a_pdf_goes_from_upload_to_a_result_with_the_real_document_model_and_the_real_llm(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    url = f"sqlite:///{tmp_path_factory.mktemp('e2e') / 'formlens.db'}"
    upgrade_to_head(url)
    settings = slow_settings().model_copy(update={"db_url": url})
    document = next(d for d in generate() if d.kind == "text-pdf" and d.template == "zgoda")
    app = create_app(settings, start_worker=False)
    try:
        with TestClient(app) as client:
            template = client.post("/v1/templates", json=body_of("zgoda")).json()
            queued = client.post(
                "/v1/extractions",
                data={"template_id": template["id"]},
                files={"file": (f"{document.id}.pdf", document.content, "application/pdf")},
            )
            assert queued.status_code == 202

            assert app.state.extraction_processor.run_once() is True

            done = client.get(queued.headers["Location"]).json()
    finally:
        app.state.database.dispose()

    assert done["status"] == "completed", done.get("error")
    assert Draft202012Validator(template["json_schema"]).is_valid(done["result"])
    assert any(value is not None for value in done["result"].values())
