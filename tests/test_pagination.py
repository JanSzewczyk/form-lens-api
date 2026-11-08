from typing import Annotated

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from fastapi_szumplate.pagination import Page, PageParams, get_page_params
from tests.conftest import make_settings


class IntPage(Page[int]):
    pass


def paged_app(page_size: int) -> TestClient:
    app = FastAPI()
    app.state.settings = make_settings(default_page_size=page_size)

    @app.get("/numbers", operation_id="list_numbers")
    def numbers(page: Annotated[PageParams, Depends(get_page_params)]) -> IntPage:
        return IntPage(items=[], total=0, limit=page.limit, offset=page.offset)

    return TestClient(app)


def test_default_limit_comes_from_settings() -> None:
    assert paged_app(7).get("/numbers").json()["limit"] == 7


def test_explicit_limit_and_offset_win() -> None:
    body = paged_app(7).get("/numbers", params={"limit": 3, "offset": 9}).json()

    assert (body["limit"], body["offset"]) == (3, 9)


def test_concrete_page_subclass_documents_its_items() -> None:
    schema = IntPage.model_json_schema()

    assert schema["properties"]["items"]["items"] == {"type": "integer"}
