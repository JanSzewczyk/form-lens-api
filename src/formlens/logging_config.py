"""Structured logging: structlog on top of stdlib logging, configured once at the entry point."""

import logging
import sys
from collections.abc import Mapping
from typing import Any, Final

import structlog
from structlog.types import EventDict, Processor

from formlens.config import Settings

SENSITIVE_PARTS: Final = ("password", "token", "authorization", "api_key", "secret", "cookie")
REDACTED: Final = "***"
_HANDLER_TAG: Final = "_formlens_handler"
# Extras uvicorn attaches to its own records; they repeat the message.
_NOISY_EXTRAS: Final = ("color_message",)


class _StdoutHandler(logging.StreamHandler[Any]):
    """Stream handler that looks `sys.stdout` up on every emit, so a swapped stream still works."""

    def __init__(self) -> None:
        logging.Handler.__init__(self)

    @property
    def stream(self) -> Any:
        """Return the current `sys.stdout`."""
        return sys.stdout

    @stream.setter
    def stream(self, value: Any) -> None:
        """Ignore assignment: the stream is always the live `sys.stdout`."""


def _redact_value(value: Any) -> Any:
    # Any mapping, read-only ones such as Starlette `Headers` too, and mappings inside sequences.
    if isinstance(value, Mapping):
        return {key: _redact_entry(key, item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_redact_value(item) for item in value]
    return value


def _redact_entry(key: object, value: Any) -> Any:
    if isinstance(key, str) and any(part in key.lower() for part in SENSITIVE_PARTS):
        return REDACTED
    return _redact_value(value)


def redact(_logger: object, _method: str, event_dict: EventDict) -> EventDict:
    """Mask the value of every key that looks sensitive, also inside nested mappings and sequences.

    This is defence in depth: a secret inside a message, a value or a traceback still leaks.
    """
    for key in list(event_dict):
        event_dict[key] = _redact_entry(key, event_dict[key])
    return event_dict


def _drop_noisy_extras(_logger: object, _method: str, event_dict: EventDict) -> EventDict:
    """Remove the extras that only duplicate the message of a stdlib record."""
    for key in _NOISY_EXTRAS:
        event_dict.pop(key, None)
    return event_dict


def configure_logging(settings: Settings) -> None:
    """Route structlog and stdlib records through one pipeline to stdout.

    Safe to call repeatedly: it replaces only the handler it installed earlier.
    """
    shared: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        redact,
    ]
    renderer: Processor
    if settings.resolved_log_format == "json":
        renderer = structlog.processors.JSONRenderer()
        # Locals are off: a frame's `scope` holds every request header, `Authorization` included.
        final: list[Processor] = [
            structlog.processors.ExceptionRenderer(structlog.tracebacks.ExceptionDictTransformer(show_locals=False))
        ]
    else:
        renderer = structlog.dev.ConsoleRenderer(
            colors=sys.stdout.isatty(), exception_formatter=structlog.dev.plain_traceback
        )  # not the rich formatter: it prints the locals
        final = []

    # Records of other libraries also keep the fields they pass as `extra=`; `redact` sees them.
    foreign: list[Processor] = [structlog.stdlib.ExtraAdder(), _drop_noisy_extras, *shared]

    structlog.configure(
        # A record below the level stops at the first processor, before any other work.
        processors=[structlog.stdlib.filter_by_level, *shared, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=False,
    )

    handler = _StdoutHandler()
    setattr(handler, _HANDLER_TAG, True)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=foreign,
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                *final,
                renderer,
            ],
        )
    )

    root = logging.getLogger()
    for existing in [h for h in root.handlers if getattr(h, _HANDLER_TAG, False)]:
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(settings.log_level)

    # uvicorn's own loggers feed the root pipeline. `uvicorn.access` is left alone: uvicorn
    # silences it with `access_log=False`, because RequestContextMiddleware writes the access line.
    for name in ("uvicorn", "uvicorn.error"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = True
