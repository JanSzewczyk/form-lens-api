"""The repository under test: the fake today, SQLite as well once it exists."""

import pytest

from formlens.extractions.domain.ports import ExtractionRepository
from tests.extractions.fakes import FakeExtractionRepository


@pytest.fixture(params=["fake"])
def repository(request: pytest.FixtureRequest) -> ExtractionRepository:  # one run per param
    """Every contract test runs once per implementation."""
    return FakeExtractionRepository()
