"""click-based CLI. See `memex-review --help`.

Daily-only; mirrors the sibling CLI shape from vault-review/agent-review.
"""

from __future__ import annotations

import datetime as dt
import sys

import click
from dateutil import parser as date_parser

from .client import collect_for_date
from .config import get_settings
from .dossier import render_dossier
from .vault import read_daily_section, remove_daily_section, write_daily_section


def _today() -> dt.date:
    return dt.datetime.now(get_settings().tz).date()


def _parse_date(s: str) -> dt.date:
    s = s.strip().lower()
    if s == "today":
        return _today()
    if s == "yesterday":
        return _today() - dt.timedelta(days=1)
    return date_parser.parse(s).date()


def _parse_range(s: str) -> list[dt.date]:
    s = s.strip().lower()
    if s == "last-week":
        end = _today()
        return [end - dt.timedelta(days=i) for i in range(6, -1, -1)]
    if ".." in s:
        a, b = s.split("..", 1)
        start = _parse_date(a)
        end = _parse_date(b)
        if end < start:
            start, end = end, start
        days = (end - start).days
        return [start + dt.timedelta(days=i) for i in range(days + 1)]
    return [_parse_date(s)]


@click.group()
@click.version_option(package_name="memex-review")
def main() -> None:
    """Daily inbox view of cf-memex captures, written into the Obsidian vault."""


@main.command()
@click.argument("date_str", default="today")
@click.option("--dry-run", is_flag=True, help="Don't write to vault.")
@click.option("--print", "do_print", is_flag=True, help="Print rendered section to stdout.")
def run(date_str: str, dry_run: bool, do_print: bool) -> None:
    """Generate the daily inbox section for DATE (default: today).

    DATE may be 'today', 'yesterday', '2026-05-14', or a range like
    '2026-05-10..2026-05-14' / 'last-week'.
    """
    for date in _parse_range(date_str):
        _run_one(date, dry_run=dry_run, do_print=do_print)


@main.command()
@click.option("--dry-run", is_flag=True)
@click.option("--print", "do_print", is_flag=True)
@click.pass_context
def today(ctx: click.Context, **kw: bool) -> None:
    """Alias for `run today`."""
    ctx.invoke(run, date_str="today", **kw)


@main.command()
@click.option("--dry-run", is_flag=True)
@click.option("--print", "do_print", is_flag=True)
@click.pass_context
def yesterday(ctx: click.Context, **kw: bool) -> None:
    """Alias for `run yesterday`."""
    ctx.invoke(run, date_str="yesterday", **kw)


def _run_one(date: dt.date, *, dry_run: bool, do_print: bool) -> None:
    s = get_settings()
    click.echo(f"\n=== {date.isoformat()} ({s.tz_name}) ===", err=True)

    thoughts = collect_for_date(date, settings=s)
    click.echo(f"  {len(thoughts)} captures in window", err=True)

    heading = f"memex-review — {date.isoformat()} — inbox"
    window_label = date.isoformat()
    section_md = render_dossier(thoughts, window_label, heading, s.tz)

    if do_print:
        click.echo(section_md)

    if dry_run:
        click.echo("  --dry-run: not writing to vault.", err=True)
        return

    path = write_daily_section(date, section_md)
    click.echo(f"  wrote section → {path}", err=True)


@main.command()
@click.argument("date_str")
def show(date_str: str) -> None:
    """Print the current memex-review section for DATE."""
    date = _parse_date(date_str)
    section = read_daily_section(date)
    if section is None:
        click.echo(f"no memex-review section for {date.isoformat()}", err=True)
        sys.exit(2)
    click.echo(section)


@main.command()
@click.argument("date_str")
def reset(date_str: str) -> None:
    """Remove the memex-review section for DATE."""
    date = _parse_date(date_str)
    if remove_daily_section(date):
        click.echo(f"removed memex-review section for {date.isoformat()}", err=True)
    else:
        click.echo(f"no memex-review section to remove for {date.isoformat()}", err=True)


if __name__ == "__main__":
    main()
