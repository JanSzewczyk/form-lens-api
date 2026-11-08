"""Fixtures of the example domain's tests."""

from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from fastapi_szumplate.library.books.repository import BookRepository, InMemoryBookRepository


@pytest.fixture
def book_repository() -> BookRepository:
    """A fresh in-memory repository, typed as the port."""
    return InMemoryBookRepository()


@pytest.fixture
def api(app: FastAPI) -> Iterator[TestClient]:
    """Client for the full app with the example domain mounted."""
    with TestClient(app) as client:
        yield client
