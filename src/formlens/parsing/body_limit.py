"""Caps the size of an upload body before the framework has read all of it."""

from collections.abc import Callable
from typing import Final

from starlette.datastructures import Headers
from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from formlens.parsing.errors import FILE_TOO_LARGE
from formlens.parsing.exceptions import FileTooLarge
from formlens.parsing.models import BYTES_PER_MB
from formlens.problems import BODY_TOO_LARGE, BodyTooLarge, domain_error_handler

# The multipart framing around the file (boundaries, part headers) is not part of the file. The body
# may exceed the limit by this much; the service checks the exact size of the file.
SLACK_BYTES: Final = 1024 * 1024

_handle_too_large = domain_error_handler({FileTooLarge: FILE_TOO_LARGE, BodyTooLarge: BODY_TOO_LARGE})

# Whether a request is one whose JSON body is capped: `(method, path)` in, yes or no out. The paths of a route that
# has a variable segment cannot be listed, so the application gives a predicate.
type JsonRule = Callable[[str, str], bool]


class BodyLimitMiddleware:
    """Pure ASGI middleware for the POST paths that take an upload, and optionally for JSON bodies.

    The upload paths are exact (`paths`, POST only) and capped at `max_upload_mb` plus the multipart slack, with a
    413 `file-too-large`. A request for which `json_rule(method, path)` is true is capped at `max_json_kb`, with a
    413 `body-too-large`; that is for routes with a small JSON body, where reading tens of megabytes only to answer
    422 is a waste. Both caps work the same way, as follows.

    A declared `Content-Length` over the cap is answered with 413 before the body is read. A body
    without one (chunked) is counted as it arrives; past the cap the framework is told the client
    went away, so it stops reading, and the answer it gives is replaced by the 413. Nothing is
    raised from `receive`, and the parser is never reached with a truncated body.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        paths: frozenset[str],
        max_upload_mb: int,
        json_rule: JsonRule | None = None,
        max_json_kb: int = 2048,
    ) -> None:
        """Guard the POST requests to `paths` (the limit plus the slack) and the requests `json_rule` names."""
        self.app = app
        self._paths = paths
        self._max_upload_mb = max_upload_mb
        self._cap = max_upload_mb * BYTES_PER_MB + SLACK_BYTES
        self._json_rule = json_rule
        self._max_json_kb = max_json_kb

    def _rule(self, scope: Scope) -> tuple[int, Exception] | None:
        """Return the cap in bytes and the error to answer with for this request, or None when it is not capped."""
        method, path = scope["method"], scope["path"]
        if method == "POST" and path in self._paths:
            return self._cap, FileTooLarge(self._max_upload_mb)
        if self._json_rule is not None and self._json_rule(method, path):
            return self._max_json_kb * 1024, BodyTooLarge(self._max_json_kb)
        return None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Pass other requests through; cap the body of the guarded one."""
        rule = self._rule(scope) if scope["type"] == "http" else None
        if rule is None:
            await self.app(scope, receive, send)
            return
        cap, error = rule

        declared = Headers(scope=scope).get("content-length")
        if declared is not None and declared.isascii() and declared.isdigit() and int(declared) > cap:
            await self._refuse(scope, receive, send, error)
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
                if received > cap:
                    exceeded = True
                    return {"type": "http.disconnect"}
            return message

        async def guarded_send(message: Message) -> None:
            nonlocal refused, started
            if exceeded and not started:
                if not refused:
                    refused = True
                    await self._refuse(scope, receive, send, error)
                return  # whatever the application answers to a cut body is dropped
            started = started or message["type"] == "http.response.start"
            await send(message)

        try:
            await self.app(scope, counting_receive, guarded_send)
        except Exception:
            if not exceeded or started:
                raise
        if exceeded and not refused and not started:
            await self._refuse(scope, receive, send, error)

    async def _refuse(self, scope: Scope, receive: Receive, send: Send, error: Exception) -> None:
        response = await _handle_too_large(Request(scope, receive), error)
        await response(scope, receive, send)
