"""Offset pagination: the page envelope and the query parameters that drive it."""

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Query
from pydantic import BaseModel, Field

from fastapi_szumplate.config import Settings, get_settings

MAX_PAGE_SIZE = 100


class Page[T](BaseModel):
    """Base of every list response. Subclass it with a concrete item type."""

    items: list[T] = Field(description="The items on this page.")
    total: int = Field(description="Number of items across all pages.", examples=[1], ge=0)
    limit: int = Field(description="Page size that was applied.", examples=[20], ge=1)
    offset: int = Field(description="Number of items skipped.", examples=[0], ge=0)


@dataclass(frozen=True, slots=True)
class PageParams:
    """A validated page request."""

    limit: int
    offset: int


def get_page_params(
    settings: Annotated[Settings, Depends(get_settings)],
    limit: Annotated[
        int | None,
        Query(
            ge=1,
            le=MAX_PAGE_SIZE,
            description=(
                f"Items per page, 1 to {MAX_PAGE_SIZE}. "
                "Defaults to the configured page size (20 unless DEFAULT_PAGE_SIZE is set)."
            ),
            examples=[20],
        ),
    ] = None,
    offset: Annotated[
        int,
        Query(ge=0, description="Items to skip from the start of the list.", examples=[0]),
    ] = 0,
) -> PageParams:
    """Read `limit` and `offset`, applying the configured default page size."""
    return PageParams(limit=limit or settings.default_page_size, offset=offset)
