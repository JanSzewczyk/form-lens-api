"""Parsing slots: how many documents are converted at the same time."""

import threading
from collections.abc import Iterator
from contextlib import contextmanager

from formlens.parsing.exceptions import ParserBusy


class ParseSlots:
    """A fixed number of slots, taken without waiting.

    A caller that finds none free is refused at once with `ParserBusy`: the model is heavy, and a
    queue of waiting requests would hold their connections and their memory. The semaphore is the
    one atomic step between "a slot is free" and "I took it".
    """

    def __init__(self, size: int) -> None:
        """Create `size` slots."""
        self._semaphore = threading.BoundedSemaphore(size)

    @contextmanager
    def hold(self) -> Iterator[None]:
        """Hold one slot for the body of the `with`; raise `ParserBusy` when none is free."""
        if not self._semaphore.acquire(blocking=False):
            raise ParserBusy
        try:
            yield
        finally:
            self._semaphore.release()
