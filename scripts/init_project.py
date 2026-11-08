"""Turn a copy of this template into your project: rename it and, optionally, drop the example.

Run it once, in the root of the copy, before the first commit:

    python scripts/init_project.py orders-api
    python scripts/init_project.py orders-api --without-example

It renames the distribution (`fastapi-szumplate` -> `orders-api`), the package
(`fastapi_szumplate` -> `orders_api`) and its directory, and rewrites every text file. With
`--without-example` it also deletes the example domain (`library/`, `tests/library/`), its
`include_library` hook, its settings and its import-linter contracts. It then deletes itself,
its test and the smoke script, and strips what only makes sense in the template. Afterwards run
`make openapi && make check`: the OpenAPI document carries the service name.

Text files mark what belongs to one audience, in a comment at the end of a line or on lines of
their own (`<!-- ... -->` in Markdown, `# ...` elsewhere):

    ... <!-- only:template -->   this line only in the template
    <!-- begin:example -->       these lines only while the example stays
    ...
    <!-- end:example -->

The audiences are `template` (always removed here), `project` (always kept), `example` (kept
unless `--without-example`) and `bare` (kept only with `--without-example`). The marker comments
themselves are removed. `--check-references` lists what still names the removed example.
"""

import argparse
import re
import shutil
import sys
from pathlib import Path

OLD_DIST = "fastapi-szumplate"
OLD_PACKAGE = "fastapi_szumplate"
OLD_TITLE = "FastAPI Szumplate"

NAME_PATTERN = re.compile(r"[a-z][a-z0-9]*(-[a-z0-9]+)*")
TEXT_SUFFIXES = {
    ".py",
    ".toml",
    ".md",
    ".yaml",
    ".yml",
    ".json",
    ".lock",
    ".sh",
    ".example",
    ".txt",
}
TEXT_NAMES = {"Makefile", "Dockerfile", ".dockerignore", ".gitignore"}
SKIP_DIRS = {
    ".git",
    ".venv",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".hypothesis",
    ".schemathesis",
    ".import_linter_cache",
    ".claude",  # local agent settings and worktrees: other checkouts, not this project's files
}
EXAMPLE_DOCS = ("docs/how-to/remove-the-example.md", "docs/how-to/swap-in-a-database.md")
# Words that name the example domain. "standard library" is the Python term and is allowed.
EXAMPLE_WORDS = re.compile(
    r"\b(?:library|include_library|books?|loans?|loans?_\w+|isbn|remove-the-example"
    r"|swap-in-a-database)\b",
    re.IGNORECASE,
)
THIS_SCRIPT = Path(__file__).resolve()
MARKER = re.compile(r"(?:<!--\s*|#\s*)(?P<kind>only|begin|end):(?P<audience>[a-z]+)(?:\s*-->)?\s*$")


def text_files(root: Path) -> list[Path]:
    """Return the files to rewrite: text files outside caches, without this script."""
    found: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file() or SKIP_DIRS & set(path.relative_to(root).parts):
            continue
        if path.resolve() == THIS_SCRIPT:
            continue
        if path.suffix in TEXT_SUFFIXES or path.name in TEXT_NAMES:
            found.append(path)
    return found


def rename_project(root: Path, dist_name: str) -> None:
    """Rewrite names in every text file and move the package directory."""
    package = dist_name.replace("-", "_")
    title = " ".join(word.capitalize() for word in dist_name.split("-"))
    for path in text_files(root):
        text = path.read_text(encoding="utf-8")
        updated = text.replace(OLD_PACKAGE, package).replace(OLD_DIST, dist_name).replace(OLD_TITLE, title)
        if updated != text:
            path.write_text(updated, encoding="utf-8")
    old_dir = root / "src" / OLD_PACKAGE
    if old_dir.exists():
        old_dir.rename(root / "src" / package)


def remove_example(root: Path, package: str) -> None:
    """Delete the example domain and everything that points at it."""
    shutil.rmtree(root / "src" / package / "library", ignore_errors=True)
    shutil.rmtree(root / "tests" / "library", ignore_errors=True)
    for name in EXAMPLE_DOCS:
        (root / name).unlink(missing_ok=True)

    main = root / "src" / package / "main.py"
    lines = main.read_text(encoding="utf-8").splitlines(keepends=True)
    main.write_text("".join(line for line in lines if "include_library" not in line), encoding="utf-8")

    config = root / "src" / package / "config.py"
    text = config.read_text(encoding="utf-8")
    text = re.sub(
        # The field is one line when it fits the line length, otherwise it is wrapped.
        r"    (?:loans_max_active_per_member|loan_days): int = Field\((?:[^\n]*\)\n|.*?\n    \)\n)",
        "",
        text,
        flags=re.DOTALL,
    )
    config.write_text(text, encoding="utf-8")

    env_example = root / ".env.example"
    kept = [
        line
        for line in env_example.read_text(encoding="utf-8").splitlines(keepends=True)
        if not line.startswith(("LOANS_MAX_ACTIVE_PER_MEMBER", "LOAN_DAYS", "# Example domain"))
    ]
    env_example.write_text("".join(kept), encoding="utf-8")

    pyproject = root / "pyproject.toml"
    # One block per top-level table, so a table after the contracts is never taken for part of one.
    blocks = re.split(r"(?=^\[)", pyproject.read_text("utf-8"), flags=re.MULTILINE)
    pyproject.write_text("".join(b for b in blocks if not _is_example_contract(b)), encoding="utf-8")


def _is_example_contract(block: str) -> bool:
    """Tell whether a `pyproject.toml` block is an import-linter contract about the example."""
    return block.startswith("[[tool.importlinter.contracts]]") and ".library" in block


def apply_markers(text: str, keep: frozenset[str]) -> str:
    """Keep the lines marked for an audience in `keep` and drop the other marked lines."""
    kept: list[str] = []
    visible: list[bool] = []
    for line in text.splitlines(keepends=True):
        marker = MARKER.search(line.rstrip("\r\n"))
        if marker is None:
            if all(visible):
                kept.append(line)
        elif marker["kind"] == "begin":
            visible.append(marker["audience"] in keep)
        elif marker["kind"] == "end":
            visible.pop()
        elif all(visible) and marker["audience"] in keep:
            kept.append(line[: marker.start()].rstrip() + "\n")
    return "".join(kept)


def apply_audience(root: Path, keep: frozenset[str]) -> None:
    """Resolve the audience markers in every text file."""
    for path in text_files(root):
        text = path.read_text(encoding="utf-8")
        updated = apply_markers(text, keep)
        if updated != text and path.suffix == ".md":
            updated = re.sub(r"\n{3,}", "\n\n", updated)  # a removed block leaves a gap
        if updated != text:
            path.write_text(updated, encoding="utf-8")


def find_example_references(root: Path, *, skip: frozenset[str] = frozenset()) -> list[str]:
    """Return `path:line: text` for every line that still names the example domain.

    `skip` lists relative paths to leave out, for a tree whose generated files are not rebuilt yet.
    """
    found: list[str] = []
    for path in text_files(root):
        relative = path.relative_to(root).as_posix()
        if relative in skip or path.name == "uv.lock":
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if EXAMPLE_WORDS.search(line.replace("standard library", "")):
                found.append(f"{relative}:{number}: {line.strip()}")
    return found


def drop_template_machinery(root: Path) -> None:
    """Delete what only makes sense in the template: this script, its test, the smoke script."""
    for name in (
        "scripts/init_project.py",
        "scripts/smoke_template.sh",
        "tests/test_init_project.py",
    ):
        (root / name).unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    """Parse the arguments and run the steps."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument(
        "name",
        nargs="?",
        help="new distribution name, lowercase with dashes, e.g. orders-api",
    )
    parser.add_argument("--without-example", action="store_true", help="also delete the example domain")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="project root (default: cwd)")
    parser.add_argument(
        "--check-references",
        action="store_true",
        help="do not change anything: list the lines that still name the example, exit 1 if any",
    )
    args = parser.parse_args(argv)

    if args.check_references:
        leftovers = find_example_references(args.root.resolve())
        print("\n".join(leftovers))
        return 1 if leftovers else 0

    if args.name is None:
        parser.error("the name argument is required")
    if not NAME_PATTERN.fullmatch(args.name):
        print(
            f"{args.name!r} is not a valid name: use lowercase letters, digits and dashes.",
            file=sys.stderr,
        )
        return 2
    root: Path = args.root.resolve()
    if not (root / "src" / OLD_PACKAGE).exists():
        print(f"No src/{OLD_PACKAGE} under {root}: was this project already renamed?", file=sys.stderr)
        return 1

    rename_project(root, args.name)
    if args.without_example:
        remove_example(root, args.name.replace("-", "_"))
    drop_template_machinery(root)
    apply_audience(root, frozenset({"project", "bare" if args.without_example else "example"}))
    print(f"Renamed to {args.name}. Next: review the contact URL in openapi.py and the copyright")
    print("holder in LICENSE, then")
    print("  uv sync --locked && make openapi && make check")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
