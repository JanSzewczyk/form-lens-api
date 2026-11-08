"""A parser that needs no model, for every test that is not about the model itself."""

import threading

from formlens.parsing.ports import ParseResult

DEFAULT_RESULT = ParseResult(
    text="# Fake page\n\nfake text",
    plain_text="Fake page fake text",
    page_count=1,
    elapsed_ms=12,
    model_id="fake/model",
)


class FakeParser:
    """Returns a fixed result, raises a given error, or blocks until a test lets it go.

    `max_running` is the most `parse` calls that were inside at the same moment. `calls` keeps the
    size and the neutral name of each call, never the bytes.
    """

    def __init__(
        self,
        result: ParseResult = DEFAULT_RESULT,
        *,
        error: Exception | None = None,
        release: threading.Event | None = None,
        block_timeout: float = 10.0,
    ) -> None:
        """Choose the answer; pass `release` to hold every call until the event is set."""
        self.result = result
        self.error = error
        self.release = release
        self.block_timeout = block_timeout
        self.calls: list[tuple[int, str]] = []
        self.running = 0
        self.max_running = 0
        self._lock = threading.Lock()

    def parse(self, content: bytes, filename: str) -> ParseResult:
        """Record the call, wait for `release` when given, then answer."""
        with self._lock:
            self.calls.append((len(content), filename))
            self.running += 1
            self.max_running = max(self.max_running, self.running)
        try:
            if self.release is not None:
                assert self.release.wait(self.block_timeout), "the test never released the parser"
            if self.error is not None:
                raise self.error
            return self.result
        finally:
            with self._lock:
                self.running -= 1
