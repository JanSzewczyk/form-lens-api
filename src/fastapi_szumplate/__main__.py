"""Start the service with `python -m fastapi_szumplate`."""

import uvicorn

from fastapi_szumplate.config import Settings
from fastapi_szumplate.logging_config import configure_logging


def main() -> None:
    """Configure logging, then run uvicorn on the app factory (which configures it again)."""
    settings = Settings()
    configure_logging(settings)
    uvicorn.run(
        "fastapi_szumplate.main:create_app",
        factory=True,
        host=settings.host,
        port=settings.port,
        reload=settings.reload,
        timeout_graceful_shutdown=settings.graceful_shutdown_seconds,
        server_header=False,  # do not announce the server software
        log_config=None,  # our handler is already installed; uvicorn must not replace it
        access_log=False,  # RequestContextMiddleware writes the access line
    )


if __name__ == "__main__":
    main()
