"""click-based CLI. See `memex-review --help`.

Daily-only; mirrors the sibling CLI shape from vault-review/agent-review.
"""

from __future__ import annotations

import datetime as dt
import sys

import click
from dateutil import parser as date_parser

from .client import collect_for_date
from .config import Settings, get_settings
from .cursor import cursor_path, filter_visible, load_cursor, save_cursor
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
    cursor = load_cursor(s)
    visible = filter_visible(thoughts, cursor)
    click.echo(
        f"  {len(visible)} visible / {len(thoughts)} fetched (cursor {cursor.isoformat()})",
        err=True,
    )

    heading = f"memex-review — {date.isoformat()} — inbox"
    window_label = date.isoformat()
    section_md = render_dossier(visible, window_label, heading, s.tz)

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


def _eod(date: dt.date, s: Settings) -> dt.datetime:
    """End-of-day in local tz (23:59:59 — matches the cursor design doc)."""
    return dt.datetime.combine(date, dt.time(23, 59, 59), tzinfo=s.tz)


def _relative_phrase(cursor: dt.datetime, s: Settings) -> str:
    today = dt.datetime.now(tz=s.tz).date()
    cdate = cursor.astimezone(s.tz).date()
    delta = (today - cdate).days
    if delta == 0:
        return "today EOD"
    if delta == 1:
        return "yesterday EOD"
    if delta > 1:
        return f"{delta} days ago EOD"
    if delta == -1:
        return "tomorrow EOD"
    return f"{-delta} days ahead EOD"


@main.command(name="process")
@click.option(
    "--through",
    "through",
    default="yesterday",
    help="Advance cursor through end of this date (default: yesterday).",
)
def process_cmd(through: str) -> None:
    """Advance the cursor to end-of-DATE local. Idempotent; refuses future dates."""
    s = get_settings()
    target_date = _parse_date(through)
    today = dt.datetime.now(tz=s.tz).date()
    if target_date >= today:
        click.echo(
            f"refusing to advance to {target_date.isoformat()}: must be yesterday or earlier",
            err=True,
        )
        sys.exit(2)

    new_cursor = _eod(target_date, s)
    has_file = cursor_path(s).exists()
    current = load_cursor(s)
    if has_file and new_cursor <= current:
        click.echo(
            f"cursor already at or past {new_cursor.isoformat()} "
            f"(current: {current.isoformat()})",
            err=True,
        )
        return

    save_cursor(s, new_cursor)
    if has_file:
        click.echo(
            f"advanced cursor: {current.isoformat()} → {new_cursor.isoformat()}",
            err=True,
        )
    else:
        click.echo(
            f"initialized cursor (bootstrap → committed): {new_cursor.isoformat()}",
            err=True,
        )


@main.command(name="cursor")
@click.option("--rewind", "rewind", default=None, help="Move cursor BACK to end-of-DATE.")
@click.option(
    "--init",
    "init",
    default=None,
    help="First-time bootstrap override; refuses if a cursor file exists.",
)
def cursor_cmd(rewind: str | None, init: str | None) -> None:
    """Show or modify the inbox cursor."""
    s = get_settings()

    if rewind is not None and init is not None:
        click.echo("--rewind and --init are mutually exclusive", err=True)
        sys.exit(2)

    if init is not None:
        if cursor_path(s).exists():
            click.echo(
                f"cursor file already exists at {cursor_path(s)}; "
                "use --rewind to move it back",
                err=True,
            )
            sys.exit(2)
        new_cursor = _eod(_parse_date(init), s)
        save_cursor(s, new_cursor)
        click.echo(f"initialized cursor: {new_cursor.isoformat()}", err=True)
        return

    if rewind is not None:
        current = load_cursor(s)
        new_cursor = _eod(_parse_date(rewind), s)
        if new_cursor >= current:
            click.echo(
                f"refusing to rewind to {new_cursor.isoformat()}: "
                f"not earlier than current cursor {current.isoformat()} "
                "(use `process` to advance forward)",
                err=True,
            )
            sys.exit(2)
        save_cursor(s, new_cursor)
        click.echo(
            f"rewound cursor: {current.isoformat()} → {new_cursor.isoformat()}",
            err=True,
        )
        return

    # Plain `cursor` — print current.
    current = load_cursor(s)
    phrase = _relative_phrase(current, s)
    if not cursor_path(s).exists():
        click.echo(f"{current.isoformat()} ({phrase}) (not yet persisted; run process to commit)")
    else:
        click.echo(f"{current.isoformat()} ({phrase})")


if __name__ == "__main__":
    main()
