"""Application factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import Depends, FastAPI
from starlette.concurrency import run_in_threadpool

from formlens.config import Settings
from formlens.database import Database
from formlens.health.readiness import install_readiness, register_readiness_check
from formlens.health.router import router as health_router
from formlens.logging_config import configure_logging
from formlens.middleware import (
    REQUEST_ID_HEADER,
    ProblemCORSMiddleware,
    RequestContextMiddleware,
    UnhandledErrorMiddleware,
)
from formlens.openapi import HEALTH_TAG, METADATA, install_openapi
from formlens.parsing.body_limit import BodyLimitMiddleware
from formlens.parsing.docling_parser import build_docling_parser
from formlens.parsing.errors import ERRORS as PARSING_ERRORS
from formlens.parsing.exceptions import ModelUnavailable
from formlens.parsing.ports import ParserFactory
from formlens.parsing.router import DOCUMENTS_TAG, PARSE_PATH
from formlens.parsing.router import router as parsing_router
from formlens.parsing.slots import ParseSlots
from formlens.problems import add_problem_handlers, register_domain_errors
from formlens.query import reject_repeated_query_parameters
from formlens.templates.errors import ERRORS as TEMPLATE_ERRORS
from formlens.templates.repository import SqliteTemplateRepository
from formlens.templates.router import TEMPLATES_TAG
from formlens.templates.router import router as templates_router

log = structlog.get_logger(__name__)

# `Retry-After` is how a client learns when to retry a busy parser, so a browser must be allowed to read it.
_EXPOSED_HEADERS = [REQUEST_ID_HEADER, "Retry-After"]


def create_app(settings: Settings | None = None, *, parser_factory: ParserFactory | None = None) -> FastAPI:
    """Build the FastAPI application.

    Building it loads nothing: the parser is built when the app starts (the lifespan), in a worker
    thread, so a model that fails to load stops the startup and never a request.

    Args:
        settings: Optional settings override, used by tests.
        parser_factory: Builds the document parser at startup, in a worker thread. The default loads
            the Docling model; tests pass a fake.

    Returns:
        The configured application.
    """
    settings = settings or Settings()
    configure_logging(settings)
    factory = parser_factory or build_docling_parser

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        try:
            application.state.parser = await run_in_threadpool(factory, settings)
        except Exception as exc:
            # Once, here; uvicorn prints the traceback when the startup fails, so none is logged. Only a
            # missing or incomplete model is cured by downloading it; any other failure gets no such hint.
            fields = (
                {"hint": "run `make download-models`, then start the service again"}
                if isinstance(exc, ModelUnavailable)
                else {}
            )
            log.error(  # noqa: TRY400
                "model_load_failed",
                backend=settings.vlm_backend,
                models_path=str(settings.models_path),
                reason=str(exc),
                **fields,
            )
            raise
        yield
        application.state.parser = None
        application.state.database.dispose()

    app = FastAPI(
        lifespan=lifespan,
        title=settings.app_name,
        docs_url="/docs" if settings.docs_enabled else None,
        redoc_url="/redoc" if settings.docs_enabled else None,
        openapi_url="/openapi.json" if settings.docs_enabled else None,
        redirect_slashes=False,
        dependencies=[Depends(reject_repeated_query_parameters)],
        openapi_tags=[HEALTH_TAG, DOCUMENTS_TAG, TEMPLATES_TAG],
        **METADATA,
    )
    app.state.settings = settings
    app.state.parser = None
    app.state.parse_slots = ParseSlots(settings.max_concurrency)
    # Building the database opens no connection and creates no file: the first query does. The tables come
    # from `make migrate`, never from the app.
    database = Database(settings.db_url)
    app.state.database = database
    app.state.template_repository = SqliteTemplateRepository(database)
    add_problem_handlers(app)
    install_openapi(app)
    install_readiness(app)
    register_domain_errors(app, PARSING_ERRORS)
    register_domain_errors(app, TEMPLATE_ERRORS)
    register_readiness_check(app, "model", lambda: _require_model(app))
    app.include_router(health_router)
    app.include_router(parsing_router)
    app.include_router(templates_router)

    # Starlette makes the last middleware added the outermost one: request context, then CORS,
    # then the 500 answer, then the body cap, so a 500 or a 413 carries the request id and the
    # CORS headers.
    app.add_middleware(BodyLimitMiddleware, paths=frozenset({PARSE_PATH}), max_upload_mb=settings.max_upload_mb)
    app.add_middleware(UnhandledErrorMiddleware)
    if settings.cors_origins:
        app.add_middleware(
            ProblemCORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_methods=["GET", "POST", "PUT", "DELETE"],
            allow_headers=[REQUEST_ID_HEADER, "Content-Type"],
            expose_headers=_EXPOSED_HEADERS,
            allow_credentials=False,
        )
    app.add_middleware(RequestContextMiddleware)
    return app


def _require_model(app: FastAPI) -> None:
    """Readiness check: the service cannot take traffic until the model is loaded."""
    if app.state.parser is None:
        raise ModelUnavailable
