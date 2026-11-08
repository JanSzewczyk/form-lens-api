"""Builds the books service for a request from the repository the app owns."""

from typing import Annotated, cast

from fastapi import Depends, Request

from fastapi_szumplate.library.books.repository import BookRepository
from fastapi_szumplate.library.books.service import BookService


def get_book_repository(request: Request) -> BookRepository:
    """Return the repository `include_library` stored on the app."""
    return cast("BookRepository", request.app.state.book_repository)


def get_book_service(
    books: Annotated[BookRepository, Depends(get_book_repository)],
) -> BookService:
    """Return the books service."""
    return BookService(books)
