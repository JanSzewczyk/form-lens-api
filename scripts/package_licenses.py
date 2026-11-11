"""Print the licence each installed package declares, as table rows for docs/licenses.md.

Usage: `uv run python scripts/package_licenses.py NAME [NAME ...]`

It reads the metadata of the installed distribution (`importlib.metadata`): the `License-Expression` field, else
the `License` field, else the `License ::` classifiers. That is what the package says about itself. It is not a
review: nobody has read the licence file, and a package may declare less than it ships.
"""

import sys
from importlib import metadata


def declared_licence(name: str) -> tuple[str, str, str]:
    """Return the version, the declared licence and the field it came from for an installed package.

    Raises:
        metadata.PackageNotFoundError: The package is not installed.
    """
    info = metadata.metadata(name)
    version = metadata.version(name)
    expression = info.get("License-Expression")
    if expression:
        return version, expression, "License-Expression"
    text = (info.get("License") or "").strip()
    if text and "\n" not in text and len(text) < 80:  # a long value is the licence text, not its name
        return version, text, "License"
    classifiers = [
        c.removeprefix("License :: ") for c in info.get_all("Classifier") or [] if c.startswith("License ::")
    ]
    if classifiers:
        return version, " / ".join(classifiers), "Classifier"
    return version, "not declared in the metadata", "none"


def main(argv: list[str]) -> int:
    """Print one row per package; return 1 when a package is not installed."""
    status = 0
    for name in argv:
        try:
            version, licence, source = declared_licence(name)
        except metadata.PackageNotFoundError:
            print(f"| {name} | not installed | - | - |")
            status = 1
            continue
        print(f"| {name} | {version} | {licence} | {source} |")
    return status


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
