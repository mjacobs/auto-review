"""click-based CLI. See `memex-review --help`.

Subcommands are stubs at this stage; see auto-review-pj5/860/zmo/9bo in beads.
"""

from __future__ import annotations

import click


@click.group()
@click.version_option(package_name="memex-review")
def main() -> None:
    """Daily recap of cf-memex captures into the Obsidian vault."""


@main.command()
@click.argument("when", required=False, default="today")
@click.option("--dry-run", is_flag=True, help="Read-only; don't write to the vault.")
@click.option("--print", "do_print", is_flag=True, help="Echo the rendered section to stdout.")
def run(when: str, dry_run: bool, do_print: bool) -> None:
    """Render and write the daily section for WHEN (today | yesterday | DATE | RANGE)."""
    raise click.ClickException("not implemented yet (auto-review-9bo)")


@main.command()
@click.option("--dry-run", is_flag=True)
@click.option("--print", "do_print", is_flag=True)
def today(dry_run: bool, do_print: bool) -> None:
    """Alias for `run today`."""
    raise click.ClickException("not implemented yet (auto-review-9bo)")


@main.command()
@click.option("--dry-run", is_flag=True)
@click.option("--print", "do_print", is_flag=True)
def yesterday(dry_run: bool, do_print: bool) -> None:
    """Alias for `run yesterday`."""
    raise click.ClickException("not implemented yet (auto-review-9bo)")


@main.command()
@click.argument("date")
def show(date: str) -> None:
    """Print the existing memex-review section for DATE, if any."""
    raise click.ClickException("not implemented yet (auto-review-9bo)")


@main.command()
@click.argument("date")
def reset(date: str) -> None:
    """Remove the memex-review section for DATE."""
    raise click.ClickException("not implemented yet (auto-review-9bo)")


if __name__ == "__main__":
    main()
