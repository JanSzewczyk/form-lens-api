"""FastAPI Szumplate package."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("fastapi-szumplate")
except PackageNotFoundError:  # pragma: no cover - only when the source tree is not installed
    __version__ = "0.0.0"

__all__ = ["__version__"]
