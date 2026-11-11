"""`python -m formlens`: no argument serves, `migrate` updates the database."""

import json
import runpy
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
import uvicorn
from sqlalchemy import inspect

from formlens import __main__ as cli
from formlens.database import Database
from formlens.migrations import current_revision, head_revision

ROOT = Path(__file__).resolve().parent.parent


def test_no_argument_serves() -> None:
    with patch.object(cli, "main", autospec=True) as serve:
        cli.run([])

    serve.assert_called_once_with()


def test_the_serve_command_serves() -> None:
    with patch.object(cli, "main", autospec=True) as serve:
        cli.run(["serve"])

    serve.assert_called_once_with()


def test_migrate_creates_the_database_at_the_head_revision(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "cli.db"
    monkeypatch.setenv("DB_URL", f"sqlite:///{path}")
    monkeypatch.chdir(tmp_path)  # no .env here

    with patch.object(cli, "main", autospec=True) as serve:
        cli.run(["migrate"])

    database = Database(f"sqlite:///{path}")
    try:
        assert current_revision(database.engine) == head_revision()
        assert "alembic_version" in inspect(database.engine).get_table_names()
    finally:
        database.dispose()
    serve.assert_not_called()


def test_the_entry_point_reads_the_command_from_the_command_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "argv", ["formlens", "migrate"])
    monkeypatch.setenv("DB_URL", f"sqlite:///{tmp_path / 'argv.db'}")
    monkeypatch.chdir(tmp_path)

    cli.cli()

    assert (tmp_path / "argv.db").exists()


def test_running_the_module_without_a_command_serves(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["formlens"])
    monkeypatch.delitem(sys.modules, "formlens.__main__")  # runpy warns about a module that is already imported
    with patch.object(uvicorn, "run", autospec=True) as run:
        runpy.run_module("formlens", run_name="__main__")

    run.assert_called_once()


def test_an_unknown_command_is_refused() -> None:
    with pytest.raises(SystemExit) as raised:
        cli.run(["drop-everything"])

    assert raised.value.code == 2


def test_the_module_runs_the_migrate_command_as_a_process(tmp_path: Path) -> None:
    """The command `make migrate` runs, end to end: it logs one line and leaves the database at the head."""
    path = tmp_path / "process.db"
    environment = {"DB_URL": f"sqlite:///{path}", "LOG_FORMAT": "json", "PATH": "/usr/bin:/bin"}

    result = subprocess.run(  # this interpreter, fixed arguments
        [sys.executable, "-m", "formlens", "migrate"],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )

    assert result.returncode == 0, result.stderr[-1500:]
    events = [json.loads(line)["event"] for line in result.stdout.splitlines() if line.startswith("{")]
    assert events == ["database_migrated"]
    assert path.exists()
