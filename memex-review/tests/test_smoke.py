"""Sanity check: package imports and CLI is wired."""

from click.testing import CliRunner

from memex_review import __version__
from memex_review.cli import main


def test_version() -> None:
    assert __version__


def test_cli_help() -> None:
    result = CliRunner().invoke(main, ["--help"])
    assert result.exit_code == 0
    assert "memex-review" in result.output.lower()
    for verb in ("run", "today", "yesterday", "show", "reset"):
        assert verb in result.output
