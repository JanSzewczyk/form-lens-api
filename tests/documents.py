"""The synthetic documents of `tests/data/` and a helper that builds a multipart body by hand."""

from collections.abc import Iterator
from pathlib import Path
from typing import Final

DATA: Final = Path(__file__).resolve().parent / "data"
BOUNDARY: Final = "formlens-test-boundary"
MULTIPART: Final = f"multipart/form-data; boundary={BOUNDARY}"

# A signature and nothing else: enough for the service to type the file, for a test that never
# reaches a real parser.
PNG_SIGNATURE: Final = b"\x89PNG\r\n\x1a\n"


def sample(name: str) -> bytes:
    """Return the bytes of one file in `tests/data/`."""
    return (DATA / name).read_bytes()


def png_of_size(size: int) -> bytes:
    """Return `size` bytes that start like a PNG, so only the size is wrong with them."""
    return PNG_SIGNATURE + bytes(size - len(PNG_SIGNATURE))


def multipart_chunks(content: bytes, *, filename: str = "upload.bin", piece: int = 64 * 1024) -> Iterator[bytes]:
    """Yield a multipart body with one `file` part in pieces, so a client sends it without Content-Length."""
    yield (
        f'--{BOUNDARY}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        "Content-Type: application/octet-stream\r\n\r\n"
    ).encode()
    for start in range(0, len(content), piece):
        yield content[start : start + piece]
    yield f"\r\n--{BOUNDARY}--\r\n".encode()


def multipart_body(content: bytes, *, filename: str = "upload.bin") -> bytes:
    """Return the same multipart body in one piece."""
    return b"".join(multipart_chunks(content, filename=filename))
