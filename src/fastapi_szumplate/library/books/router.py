"""HTTP routes of the books module: parse, call one service method, shape the response."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Response, status

from fastapi_szumplate.library.books.dependencies import get_book_service
from fastapi_szumplate.library.books.errors import ISBN_ALREADY_EXISTS
from fastapi_szumplate.library.books.schemas import (
    BookCreate,
    BookPage,
    BookResponse,
    BookUpdate,
)
from fastapi_szumplate.library.books.service import BookService
from fastapi_szumplate.library.constants import API_PREFIX, BOOK_NOT_FOUND
from fastapi_szumplate.pagination import PageParams, get_page_params
from fastapi_szumplate.problems import VALIDATION_ERROR, malformed_body_response, problem_response

# The version prefix is part of the router, so the route template in logs is the full path.
router = APIRouter(prefix=f"{API_PREFIX}/books", tags=["books"])

BookId = Annotated[UUID, Path(description="Identifier of the book.")]
Service = Annotated[BookService, Depends(get_book_service)]


@router.post(
    "",
    operation_id="create_book",
    status_code=status.HTTP_201_CREATED,
    responses={
        201: {
            "description": "The book was created.",
            "headers": {
                "Location": {
                    "description": "URL of the new book.",
                    "schema": {"type": "string"},
                }
            },
            "links": {
                "GetBook": {
                    "operationId": "get_book",
                    "parameters": {"book_id": "$response.body#/id"},
                    "description": "Fetch the book that was just created.",
                },
                "UpdateBook": {
                    "operationId": "update_book",
                    "parameters": {"book_id": "$response.body#/id"},
                    "description": "Change the title or author of the new book.",
                },
                "LendBook": {
                    "operationId": "create_loan",
                    "requestBody": {"book_id": "$response.body#/id", "member_id": "member-1"},
                    "description": "Lend the new book to a member.",
                },
            },
        },
        400: malformed_body_response(),
        409: problem_response(ISBN_ALREADY_EXISTS),
        422: problem_response(VALIDATION_ERROR),
    },
)
def create_book(body: BookCreate, response: Response, service: Service) -> BookResponse:
    """Add a book to the catalogue.

    The ISBN must not belong to another book. The capacity (`copies`) cannot be changed later.
    """
    book = service.create(isbn=body.isbn, title=body.title, author=body.author, copies=body.copies)
    response.headers["Location"] = f"{API_PREFIX}/books/{book.id}"
    return BookResponse.from_domain(book)


@router.get(
    "",
    operation_id="list_books",
    responses={422: problem_response(VALIDATION_ERROR)},
)
def list_books(page: Annotated[PageParams, Depends(get_page_params)], service: Service) -> BookPage:
    """List books, oldest first, one page at a time."""
    books, total = service.list_page(limit=page.limit, offset=page.offset)
    return BookPage(
        items=[BookResponse.from_domain(b) for b in books],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get(
    "/{book_id}",
    operation_id="get_book",
    responses={404: problem_response(BOOK_NOT_FOUND), 422: problem_response(VALIDATION_ERROR)},
)
def get_book(book_id: BookId, service: Service) -> BookResponse:
    """Fetch one book by its id."""
    return BookResponse.from_domain(service.get(book_id))


@router.put(
    "/{book_id}",
    operation_id="update_book",
    responses={
        400: malformed_body_response(),
        404: problem_response(BOOK_NOT_FOUND),
        422: problem_response(VALIDATION_ERROR),
    },
)
def update_book(book_id: BookId, body: BookUpdate, service: Service) -> BookResponse:
    """Replace the title and author of a book.

    The ISBN and the number of copies are fixed; to change them, add a new book.
    """
    return BookResponse.from_domain(service.update(book_id, title=body.title, author=body.author))
