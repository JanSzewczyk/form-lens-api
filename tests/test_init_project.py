import re
import shutil
import tomllib
from pathlib import Path

import pytest

from scripts import init_project

ROOT = Path(__file__).resolve().parent.parent


IGNORED = shutil.ignore_patterns(
    ".git",
    ".venv",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".hypothesis",
    ".schemathesis",
    ".import_linter_cache",
    ".coverage*",
    ".env",
    ".openapi-base.json",
)


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A scratch copy of the whole template, without caches and environments."""
    target = tmp_path / "project"
    shutil.copytree(ROOT, target, ignore=IGNORED)
    return target


def test_rename_moves_the_package_and_rewrites_every_name(project: Path) -> None:
    assert init_project.main(["orders-api", "--root", str(project)]) == 0

    assert (project / "src" / "orders_api" / "main.py").exists()
    assert not (project / "src" / "fastapi_szumplate").exists()
    for path in project.rglob("*"):
        if path.is_file() and path.suffix in {".py", ".toml", ".md", ".example"}:
            text = path.read_text(encoding="utf-8")
            assert "fastapi_szumplate" not in text, path
            assert "fastapi-szumplate" not in text, path
    pyproject = tomllib.loads((project / "pyproject.toml").read_text(encoding="utf-8"))
    assert pyproject["project"]["name"] == "orders-api"
    assert pyproject["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"] == ["src/orders_api"]


def test_rename_leaves_other_checkouts_under_claude_alone(project: Path) -> None:
    other = project / ".claude" / "worktrees" / "feature" / "main.py"
    other.parent.mkdir(parents=True)
    other.write_text("import fastapi_szumplate\n", encoding="utf-8")

    init_project.main(["orders-api", "--root", str(project)])

    assert other.read_text(encoding="utf-8") == "import fastapi_szumplate\n"


def test_without_example_removes_the_domain_its_hook_settings_and_contracts(
    project: Path,
) -> None:
    assert init_project.main(["orders-api", "--without-example", "--root", str(project)]) == 0

    package = project / "src" / "orders_api"
    assert not (package / "library").exists()
    assert not (project / "tests" / "library").exists()
    assert "library" not in (package / "main.py").read_text(encoding="utf-8")
    config = (package / "config.py").read_text(encoding="utf-8")
    assert "loan_days" not in config
    assert "default_page_size" in config
    assert "LOAN" not in (project / ".env.example").read_text(encoding="utf-8")
    contracts = tomllib.loads((project / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["importlinter"][
        "contracts"
    ]
    assert contracts
    assert all(".library" not in str(contract) for contract in contracts)


def test_without_example_keeps_a_table_that_follows_the_contracts(project: Path) -> None:
    pyproject = project / "pyproject.toml"
    pyproject.write_text(pyproject.read_text(encoding="utf-8") + "\n[tool.after_contracts]\nkept = true\n", "utf-8")

    init_project.main(["orders-api", "--without-example", "--root", str(project)])

    assert tomllib.loads(pyproject.read_text(encoding="utf-8"))["tool"]["after_contracts"] == {"kept": True}


def test_without_example_leaves_no_line_that_names_the_example(project: Path) -> None:
    init_project.main(["orders-api", "--without-example", "--root", str(project)])

    # openapi.json is rebuilt by `make openapi`, which scripts/smoke_template.sh runs and checks.
    leftovers = init_project.find_example_references(project, skip=frozenset({"openapi.json"}))
    assert leftovers == []
    for name in init_project.EXAMPLE_DOCS:
        assert not (project / name).exists(), name


def test_a_removed_block_leaves_no_run_of_blank_lines_in_the_docs(project: Path) -> None:
    init_project.main(["orders-api", "--without-example", "--root", str(project)])

    for path in project.rglob("*.md"):
        if ".venv" not in path.parts:
            assert "\n\n\n" not in path.read_text(encoding="utf-8"), path


@pytest.mark.parametrize("flags", [[], ["--without-example"]], ids=["rename", "bare"])
def test_the_project_does_not_mention_the_template_tools_it_no_longer_has(project: Path, flags: list[str]) -> None:
    init_project.main(["orders-api", *flags, "--root", str(project)])

    tools = re.compile(r"init_project|smoke[_-]template|template-smoke")
    for path in init_project.text_files(project):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            assert tools.search(line) is None, f"{path.relative_to(project)}:{number}: {line}"


def test_the_reference_finder_reports_the_line_that_names_the_example(project: Path) -> None:
    (project / "NOTES.md").write_text("fine\nlend a Book\nthe standard library\n", encoding="utf-8")

    leftovers = init_project.find_example_references(project)

    assert "NOTES.md:2: lend a Book" in leftovers
    assert not any(line.startswith("NOTES.md:3") for line in leftovers)


def test_check_references_exits_nonzero_while_the_example_is_still_there(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert init_project.main(["--check-references", "--root", str(project)]) == 1
    assert "library" in capsys.readouterr().out


def test_rename_only_keeps_the_example_and_its_docs(project: Path) -> None:
    init_project.main(["orders-api", "--root", str(project)])

    assert (project / "src" / "orders_api" / "library").is_dir()
    for name in init_project.EXAMPLE_DOCS:
        assert (project / name).exists(), name
    problem_types = (project / "docs" / "reference" / "problem-types.md").read_text("utf-8")
    assert "`book-not-found`" in problem_types


def test_without_example_keeps_the_problem_types_of_the_core(project: Path) -> None:
    init_project.main(["orders-api", "--without-example", "--root", str(project)])

    problem_types = (project / "docs" / "reference" / "problem-types.md").read_text("utf-8")
    assert "`validation-error`" in problem_types
    assert "`service-not-ready`" in problem_types
    assert "`book-not-found`" not in problem_types


@pytest.mark.parametrize("flags", [[], ["--without-example"]], ids=["rename", "bare"])
def test_the_template_only_machinery_is_removed(project: Path, flags: list[str]) -> None:
    assert init_project.main(["orders-api", *flags, "--root", str(project)]) == 0

    assert not (project / "scripts" / "init_project.py").exists()
    assert not (project / "scripts" / "smoke_template.sh").exists()
    assert not (project / "tests" / "test_init_project.py").exists()
    ci = (project / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "template-smoke" not in ci
    assert "free-threaded" in ci
    makefile = (project / "Makefile").read_text(encoding="utf-8")
    assert "smoke" not in makefile
    readme = (project / "README.md").read_text(encoding="utf-8")
    assert "## Use it" not in readme
    assert "smoke-template" not in readme
    assert "## Run it" in readme


@pytest.mark.parametrize("flags", [[], ["--without-example"]], ids=["rename", "bare"])
def test_no_marker_comment_survives_in_the_project(project: Path, flags: list[str]) -> None:
    init_project.main(["orders-api", *flags, "--root", str(project)])

    for path in init_project.text_files(project):
        for line in path.read_text(encoding="utf-8").splitlines():
            assert init_project.MARKER.search(line) is None, f"{path}: {line}"


MARKED = """\
keep
<!-- begin:example -->
only with the example
<!-- end:example -->
<!-- begin:bare -->
only without it
<!-- begin:template -->
never
<!-- end:template -->
<!-- end:bare -->
| row | <!-- only:example -->
make: target  # only:bare
"""


@pytest.mark.parametrize(
    ("keep", "expected"),
    [
        ({"example"}, "keep\nonly with the example\n| row |\n"),
        ({"bare"}, "keep\nonly without it\nmake: target\n"),
        (set(), "keep\n"),
    ],
    ids=["example", "bare", "neither"],
)
def test_markers_keep_the_lines_of_the_chosen_audience(keep: set[str], expected: str) -> None:
    assert init_project.apply_markers(MARKED, frozenset(keep)) == expected


@pytest.mark.parametrize("name", ["Orders", "orders_api", "orders-", "1orders", ""])
def test_an_invalid_name_is_refused(project: Path, name: str) -> None:
    assert init_project.main([name, "--root", str(project)]) == 2
    assert (project / "src" / "fastapi_szumplate").exists()


def test_running_it_twice_is_refused(project: Path) -> None:
    init_project.main(["orders-api", "--root", str(project)])

    assert init_project.main(["billing-api", "--root", str(project)]) == 1
