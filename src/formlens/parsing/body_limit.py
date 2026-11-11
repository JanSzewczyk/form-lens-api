"""Caps the size of an upload body before the framework has read all of it."""

from typing import Final

from starlette.datastructures import Headers
from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from formlens.parsing.errors import FILE_TOO_LARGE
from formlens.parsing.exceptions import FileTooLarge
from formlens.parsing.models import BYTES_PER_MB
from formlens.problems import domain_error_handler

# The multipart framing around the file (boundaries, part headers) is not part of the file. The body
# may exceed the limit by this much; the service checks the exact size of the file.
SLACK_BYTES: Final = 1024 * 1024

_handle_too_large = domain_error_handler({FileTooLarge: FILE_TOO_LARGE})


class BodyLimitMiddleware:
    """Pure ASGI middleware for the POST paths that take an upload.

    A declared `Content-Length` over the cap is answered with 413 before the body is read. A body
    without one (chunked) is counted as it arrives; past the cap the framework is told the client
    went away, so it stops reading, and the answer it gives is replaced by the 413. Nothing is
    raised from `receive`, and the parser is never reached with a truncated body.
    """

    def __init__(self, app: ASGIApp, *, paths: frozenset[str], max_upload_mb: int) -> None:
        """Guard the POST requests to `paths`; the cap is the limit plus the multipart slack."""
        self.app = app
        self._paths = paths
        self._max_upload_mb = max_upload_mb
        self._cap = max_upload_mb * BYTES_PER_MB + SLACK_BYTES

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Pass other requests through; cap the body of the guarded one."""
        if scope["type"] != "http" or scope["method"] != "POST" or scope["path"] not in self._paths:
            await self.app(scope, receive, send)
            return

        declared = Headers(scope=scope).get("content-length")
        if declared is not None and declared.isascii() and declared.isdigit() and int(declared) > self._cap:
            await self._refuse(scope, receive, send)
            return

        received = 0
        exceeded = False
        refused = False
        started = False  # the application began its own answer before the cap was hit

        async def counting_receive() -> Message:
            nonlocal received, exceeded
            if exceeded:
                return {"type": "http.disconnect"}
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self._cap:
                    exceeded = True
                    return {"type": "http.disconnect"}
            return message

        async def guarded_send(message: Message) -> None:
            nonlocal refused, started
            if exceeded and not started:
                if not refused:
                    refused = True
                    await self._refuse(scope, receive, send)
                return  # whatever the application answers to a cut body is dropped
            started = started or message["type"] == "http.response.start"
            await send(message)

        try:
            await self.app(scope, counting_receive, guarded_send)
        except Exception:
            if not exceeded or started:
                raise
        if exceeded and not refused and not started:
            await self._refuse(scope, receive, send)

    async def _refuse(self, scope: Scope, receive: Receive, send: Send) -> None:
        response = await _handle_too_large(Request(scope, receive), FileTooLarge(self._max_upload_mb))
        await response(scope, receive, send)
