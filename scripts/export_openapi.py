"""Write the app's OpenAPI document to `openapi.json`, or check that the committed one is current.

The document is generated from the app and never edited by hand. The settings come from the code
defaults only, never from `.env` or environment variables, so the output is the same on every machine.

Usage: `python scripts/export_openapi.py [--check] [PATH]`
"""

import argparse
import json
import sys
from pathlib import Path

from formlens.config import Settings
from formlens.main import create_app

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "openapi.json"


def render() -> str:
    """Return the OpenAPI document as stable JSON: sorted keys, two-space indent, final newline."""
    app = create_app(Settings.model_construct())
    return json.dumps(app.openapi(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    """Write the document, or with `--check` fail when the file on disk differs."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?", type=Path, default=DEFAULT_PATH)
    parser.add_argument("--check", action="store_true", help="exit 1 if the file is out of date")
    args = parser.parse_args(argv)

    document = render()
    if args.check:
        if not args.path.exists() or args.path.read_text(encoding="utf-8") != document:
            print(f"{args.path} is out of date; run `make openapi` and commit it.", file=sys.stderr)
            return 1
        return 0
    args.path.write_text(document, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
