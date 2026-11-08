"""The child process of the offline test: it records every attempt to reach a network, then does its work.

`python -I tests/offline_child.py <mode> <report.json>`. It is a script, not a test module, because
`HF_HUB_OFFLINE` is a constant that `huggingface_hub` reads when it is imported: the check needs an
interpreter that has imported neither `formlens` nor Docling when the guard goes in. The script imports
nothing from the project before `install_the_guard()` and nothing from `tests`.

Modes:
    probe  make three deliberate attempts (`connect`, `create_connection`, `getaddrinfo`) so the parent
           can show that the guard sees them. It loads no model.
    parse  start the real app, which loads the model from `MODELS_PATH` for `VLM_BACKEND`, and parse
           two documents through it.

The report is a JSON file, not stdout, so the log lines and warnings of the libraries cannot corrupt it.
"""

import contextlib
import json
import os
import socket
import sys
from pathlib import Path
from typing import Any

ATTEMPTS: list[dict[str, str]] = []
DATA = Path(__file__).resolve().parent / "data"


def install_the_guard() -> None:
    """Record every attempt to connect or resolve a name, then fail it. Nothing reaches a network."""

    def guard(call: str, *, method: bool = False) -> Any:
        def refuse(*args: Any, **kwargs: Any) -> Any:
            shown = args[1:] if method else args  # a method gets the socket first
            ATTEMPTS.append({"call": call, "arguments": repr((shown, kwargs))})
            msg = f"network access blocked: {call}"
            raise OSError(msg)

        return refuse

    socket.socket.connect = guard("connect", method=True)  # type: ignore[method-assign]
    socket.socket.connect_ex = guard("connect_ex", method=True)  # type: ignore[method-assign]
    socket.create_connection = guard("create_connection")
    socket.getaddrinfo = guard("getaddrinfo")
    socket.gethostbyname = guard("gethostbyname")


def probe() -> dict[str, Any]:
    """Try each guarded call once; a guard that records nothing here would make the real test worthless."""
    for attempt in (
        lambda: socket.socket().connect(("127.0.0.1", 9)),
        lambda: socket.create_connection(("127.0.0.1", 9)),
        lambda: socket.getaddrinfo("example.invalid", 80),
    ):
        with contextlib.suppress(OSError):
            attempt()
    return {}


def parse() -> dict[str, Any]:
    """Load the real model through the app's lifespan and parse a PDF and a PNG."""
    from fastapi.testclient import TestClient

    from formlens.config import Settings
    from formlens.main import create_app

    settings = Settings(
        _env_file=None,
        environment="test",
        models_path=Path(os.environ["MODELS_PATH"]),
        vlm_backend=os.environ["VLM_BACKEND"],  # type: ignore[arg-type]
    )
    responses = []
    with TestClient(create_app(settings)) as client:
        for name, media_type in (("text_layer.pdf", "application/pdf"), ("sample.png", "image/png")):
            reply = client.post("/v1/documents/parse", files={"file": (name, (DATA / name).read_bytes(), media_type)})
            body = reply.json()
            responses.append(
                {
                    "file": name,
                    "status": reply.status_code,
                    "page_count": body.get("page_count"),
                    "text": body.get("text"),
                }
            )
    return {"hf_hub_offline": os.environ.get("HF_HUB_OFFLINE"), "responses": responses}


def main(mode: str, report_path: str) -> None:
    """Install the guard, run the mode and write the attempts and the mode's findings to `report_path`."""
    install_the_guard()
    findings = {"probe": probe, "parse": parse}[mode]()
    Path(report_path).write_text(json.dumps({"attempts": ATTEMPTS, **findings}), encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
