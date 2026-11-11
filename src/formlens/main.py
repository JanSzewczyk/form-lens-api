"""Application factory."""

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import timedelta

import structlog
from fastapi import Depends, FastAPI
from starlette.concurrency import run_in_threadpool

from formlens.config import Settings
from formlens.database import Database
from formlens.extractions.adapters.deadline import ThreadDeadline
from formlens.extractions.adapters.ollama_extractor import OllamaFieldExtractor
from formlens.extractions.adapters.parsing_text_source import ParsingTextSource
from formlens.extractions.adapters.sqlite_repository import SqliteExtractionRepository
from formlens.extractions.domain.ports import FieldExtractor
from formlens.extractions.entrypoints.errors import ERRORS as EXTRACTION_ERRORS
from formlens.extractions.entrypoints.router import EXTRACTIONS_PATH, EXTRACTIONS_TAG
from formlens.extractions.entrypoints.router import router as extractions_router
from formlens.extractions.entrypoints.worker import ExtractionWorker
from formlens.extractions.service_layer.processor import ExtractionProcessor, ProcessorConfig
from formlens.health.readiness import install_readiness, register_readiness_check
from formlens.health.router import router as health_router
from formlens.logging_config import configure_logging
from formlens.middleware import (
    REQUEST_ID_HEADER,
    ProblemCORSMiddleware,
    RequestContextMiddleware,
    UnhandledErrorMiddleware,
)
from formlens.migrations import HINT as MIGRATE_HINT
from formlens.migrations import DatabaseNotAtHead, assert_at_head
from formlens.openapi import HEALTH_TAG, METADATA, install_openapi
from formlens.parsing.body_limit import BodyLimitMiddleware
from formlens.parsing.docling_parser import build_docling_parser
from formlens.parsing.errors import ERRORS as PARSING_ERRORS
from formlens.parsing.exceptions import ModelUnavailable
from formlens.parsing.ports import ParserFactory
from formlens.parsing.router import DOCUMENTS_TAG, PARSE_PATH
from formlens.parsing.router import router as parsing_router
from formlens.parsing.service import DocumentService
from formlens.parsing.slots import ParseSlots
from formlens.problems import add_problem_handlers, register_domain_errors
from formlens.query import reject_repeated_query_parameters
from formlens.templates.errors import ERRORS as TEMPLATE_ERRORS
from formlens.templates.repository import SqliteTemplateRepository
from formlens.templates.router import TEMPLATES_TAG, is_template_write
from formlens.templates.router import router as templates_router

log = structlog.get_logger(__name__)

# `Retry-After` is how a client learns when to retry a busy parser, so a browser must be allowed to read it.
_EXPOSED_HEADERS = [REQUEST_ID_HEADER, "Retry-After", "Location"]

type ExtractorFactory = Callable[[Settings], FieldExtractor]

# Seconds of the graceful-shutdown budget kept for the server's own work after the worker has stopped.
_SHUTDOWN_MARGIN_SECONDS = 2


def build_ollama_extractor(settings: Settings) -> FieldExtractor:
    """Build the default extractor: the local model named in the settings."""
    return OllamaFieldExtractor(
        base_url=settings.llm_base_url, model=settings.llm_model, timeout_seconds=settings.llm_timeout_seconds
    )


def create_app(
    settings: Settings | None = None,
    *,
    parser_factory: ParserFactory | None = None,
    extractor_factory: ExtractorFactory | None = None,
    start_worker: bool = True,
) -> FastAPI:
    """Build the FastAPI application.

    Building it loads nothing and touches no database: at start (the lifespan) it checks that the database
    is at the newest revision, loads the parser in a worker thread, recovers the jobs a stop left running and
    starts the worker. A failure there stops the startup and never a request.

    Args:
        settings: Optional settings override, used by tests.
        parser_factory: Builds the document parser at startup, in a worker thread. The default loads
            the Docling model; tests pass a fake.
        extractor_factory: Builds the field extractor at startup. The default talks to the local Ollama;
            tests pass a fake.
        start_worker: Start the background worker. Tests turn it off and call `run_once` themselves.

    Returns:
        The configured application.
    """
    settings = settings or Settings()
    configure_logging(settings)
    factory = parser_factory or build_docling_parser
    make_extractor = extractor_factory or build_ollama_extractor
    # Building the database opens no connection and creates no file: the first query does. The tables come
    # from `make migrate`, never from the app.
    database = Database(settings.db_url)
    extraction_repository = SqliteExtractionRepository(database)

    @asynccontextmanager
    async def run(application: FastAPI) -> AsyncIterator[None]:
        # The cheap check first: a missing migration is known before the model has loaded.
        try:
            await run_in_threadpool(assert_at_head, database)
        except DatabaseNotAtHead as exc:
            log.error(  # noqa: TRY400
                "database_not_migrated", current=exc.current, head=exc.head, db_url=settings.db_url, hint=MIGRATE_HINT
            )
            raise
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
        extractor = make_extractor(settings)
        text_source = ParsingTextSource(
            DocumentService(
                application.state.parser, application.state.parse_slots, max_upload_mb=settings.max_upload_mb
            ),
            max_upload_mb=settings.max_upload_mb,
        )
        processor = ExtractionProcessor(
            extraction_repository,
            text_source,
            extractor,
            ThreadDeadline(),
            ProcessorConfig(
                max_attempts=settings.job_max_attempts,
                job_timeout_seconds=settings.job_timeout_seconds,
                result_ttl=timedelta(hours=settings.result_ttl_hours),
                max_input_chars=settings.llm_max_input_chars,
            ),
        )
        application.state.extraction_processor = processor
        await run_in_threadpool(processor.recover)
        worker = ExtractionWorker(processor, poll_interval_seconds=settings.job_poll_interval_seconds)
        if start_worker:
            worker.start()
        yield
        await worker.stop(max(0.0, settings.graceful_shutdown_seconds - _SHUTDOWN_MARGIN_SECONDS))
        close = getattr(extractor, "close", None)
        if callable(close):
            close()
        application.state.parser = None

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        try:
            async with run(application):
                yield
        finally:
            # Also when the start failed after the head check opened a connection.
            database.dispose()

    app = FastAPI(
        lifespan=lifespan,
        title=settings.app_name,
        docs_url="/docs" if settings.docs_enabled else None,
        redoc_url="/redoc" if settings.docs_enabled else None,
        openapi_url="/openapi.json" if settings.docs_enabled else None,
        redirect_slashes=False,
        dependencies=[Depends(reject_repeated_query_parameters)],
        openapi_tags=[HEALTH_TAG, DOCUMENTS_TAG, TEMPLATES_TAG, EXTRACTIONS_TAG],
        **METADATA,
    )
    app.state.settings = settings
    app.state.parser = None
    app.state.parse_slots = ParseSlots(settings.max_concurrency)
    app.state.database = database
    app.state.extraction_repository = extraction_repository
    app.state.template_repository = SqliteTemplateRepository(database)
    add_problem_handlers(app)
    install_openapi(app)
    install_readiness(app)
    register_domain_errors(app, PARSING_ERRORS)
    register_domain_errors(app, TEMPLATE_ERRORS)
    register_domain_errors(app, EXTRACTION_ERRORS)
    register_readiness_check(app, "model", lambda: _require_model(app))
    app.include_router(health_router)
    app.include_router(parsing_router)
    app.include_router(templates_router)
    app.include_router(extractions_router)

    # Starlette makes the last middleware added the outermost one: request context, then CORS,
    # then the 500 answer, then the body cap, so a 500 or a 413 carries the request id and the
    # CORS headers.
    app.add_middleware(
        BodyLimitMiddleware,
        paths=frozenset({PARSE_PATH, EXTRACTIONS_PATH}),
        max_upload_mb=settings.max_upload_mb,
        json_rule=is_template_write,
        max_json_kb=settings.max_json_body_kb,
    )
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
