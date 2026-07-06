"""click-based CLI. See `vault-review --help`."""

from __future__ import annotations

import datetime as dt
import sys
import traceback

import click
from dateutil import parser as date_parser

from .config import get_settings
from .dossier import build_events, render_events
from .gitdelta import collect_events
from .persist import persist_daily, persist_weekly
from .runlog import record_best_effort, record_job_run
from .vault import (
    read_daily_section,
    read_weekly_section,
    remove_daily_section,
    remove_weekly_section,
    write_daily_section,
    write_weekly_section,
)
from .weekly import day_date_range, parse_week, week_date_range

# ─── date helpers ────────────────────────────────────────────────────────────


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


# ─── root group ──────────────────────────────────────────────────────────────


@click.group(invoke_without_command=False)
@click.version_option()
def main() -> None:
    """vault-review — daily and weekly narrative recaps of vault git activity."""


# ─── run (daily) ─────────────────────────────────────────────────────────────


@main.command()
@click.argument("date_str", default="today")
@click.option("--dry-run", is_flag=True, help="Don't write to vault.")
@click.option("--print", "do_print", is_flag=True, help="Print rendered section to stdout.")
def run(date_str: str, dry_run: bool, do_print: bool) -> None:
    """Generate a daily dossier for DATE (default: today).

    DATE may be 'today', 'yesterday', '2026-05-14', or a range like
    '2026-05-10..2026-05-14' / 'last-week'.
    """
    dates = _parse_range(date_str)
    for date in dates:
        _run_one(date, dry_run=dry_run, do_print=do_print)


# Convenience aliases


@main.command()
@click.option("--dry-run", is_flag=True)
@click.option("--print", "do_print", is_flag=True)
@click.pass_context
def today(ctx: click.Context, **kw) -> None:
    """Alias for `run today`."""
    ctx.invoke(run, date_str="today", **kw)


@main.command()
@click.option("--dry-run", is_flag=True)
@click.option("--print", "do_print", is_flag=True)
@click.pass_context
def yesterday(ctx: click.Context, **kw) -> None:
    """Alias for `run yesterday`."""
    ctx.invoke(run, date_str="yesterday", **kw)


def _run_one(
    date: dt.date,
    *,
    dry_run: bool,
    do_print: bool,
) -> None:
    s = get_settings()
    started_at = dt.datetime.now(tz=dt.UTC)
    click.echo(f"\n=== {date.isoformat()} ({s.tz_name}) ===", err=True)

    try:
        start, end = day_date_range(date)
        events = collect_events(s.vault_path, start, end)
        click.echo(f"  {len(events)} events in window", err=True)

        # Build the self-describing event rows ONCE (summaries read from the
        # working tree here) and render from them, so the markdown section and
        # the persisted daily_digests row stay byte-consistent (hg6.7).
        built = build_events(s.vault_path, events)
        heading = f"vault-review — {date.isoformat()}"
        window_label = date.isoformat()
        section_md = render_events(built, window_label, heading)

        if do_print:
            click.echo(section_md)

        if dry_run:
            click.echo("  --dry-run: not writing to vault, no rows, no job_runs row.", err=True)
            return

        path = write_daily_section(date, section_md)
        # Persist the row (the store the renderer projects from). Loud on
        # failure — the markdown already landed, so the note is intact, but a
        # failed row-write fails the run (records an 'error' job_run below).
        persisted = persist_daily(
            s, digest_date=date, window_start=start, window_end=end, events=built
        )
    except Exception as exc:
        if not dry_run:
            record_best_effort(
                s,
                job_name=s.daily_job_name,
                started_at=started_at,
                status="error",
                summary={
                    "date": date.isoformat(),
                    "error": f"{type(exc).__name__}: {exc}",
                    "trace": traceback.format_exc(limit=5),
                },
            )
        raise

    record_job_run(
        s,
        job_name=s.daily_job_name,
        started_at=started_at,
        status="ok",
        summary={
            "date": date.isoformat(),
            "events": len(events),
            "note_path": str(path),
            "row_persisted": persisted,
        },
    )
    click.echo(
        f"  wrote section → {path}; "
        f"{'daily_digests row upserted; ' if persisted else 'no DSN (no row); '}"
        "job_runs row recorded.",
        err=True,
    )


# ─── run-weekly ──────────────────────────────────────────────────────────────


@main.command("run-weekly")
@click.argument("week_str", default="this-week")
@click.option("--dry-run", is_flag=True, help="Don't write to vault.")
@click.option("--print", "do_print", is_flag=True, help="Print rendered section to stdout.")
def run_weekly(week_str: str, dry_run: bool, do_print: bool) -> None:
    """Generate a weekly dossier for WEEK (default: this-week).

    WEEK may be 'this-week', 'last-week', or 'YYYY-W##'.
    """
    try:
        week_label = parse_week(week_str)
    except ValueError as exc:
        click.echo(f"error: {exc}", err=True)
        sys.exit(2)
    _run_weekly_one(week_label, dry_run=dry_run, do_print=do_print)


def _run_weekly_one(
    week_label: str,
    *,
    dry_run: bool,
    do_print: bool,
) -> None:
    s = get_settings()
    started_at = dt.datetime.now(tz=dt.UTC)
    click.echo(f"\n=== {week_label} ({s.tz_name}) ===", err=True)

    try:
        start, end = week_date_range(week_label)
        events = collect_events(s.vault_path, start, end)
        click.echo(f"  {len(events)} events in window", err=True)

        built = build_events(s.vault_path, events)
        heading = f"vault-review weekly — {week_label}"
        window_label = f"7d ({week_label})"
        section_md = render_events(built, window_label, heading)

        # Append synthesis stub per vault-agent convention (ADR 006). NB: the
        # synthesis stub is a markdown-only affordance and is NOT part of the
        # persisted events (it carries no git-delta signal) — the renderer's
        # weekly port re-adds it around the row-rendered dossier (hg6.7).
        section_md = section_md.rstrip() + (
            "\n\n## synthesis\n\n"
            "_To be authored in a separate 1:1 review session over the dossier "
            "above (see [[decisions/006-checkin-to-delta-recap]])._\n"
        )

        if do_print:
            click.echo(section_md)

        if dry_run:
            click.echo("  --dry-run: not writing to vault, no rows, no job_runs row.", err=True)
            return

        path = write_weekly_section(week_label, section_md)
        persisted = persist_weekly(
            s, week_label=week_label, window_start=start, window_end=end, events=built
        )
    except Exception as exc:
        if not dry_run:
            record_best_effort(
                s,
                job_name=s.weekly_job_name,
                started_at=started_at,
                status="error",
                summary={
                    "week_label": week_label,
                    "error": f"{type(exc).__name__}: {exc}",
                    "trace": traceback.format_exc(limit=5),
                },
            )
        raise

    record_job_run(
        s,
        job_name=s.weekly_job_name,
        started_at=started_at,
        status="ok",
        summary={
            "week_label": week_label,
            "events": len(events),
            "note_path": str(path),
            "row_persisted": persisted,
        },
    )
    click.echo(
        f"  wrote section → {path}; "
        f"{'weekly_digests row upserted; ' if persisted else 'no DSN (no row); '}"
        "job_runs row recorded.",
        err=True,
    )


# ─── show / show-weekly ───────────────────────────────────────────────────────


@main.command()
@click.argument("date_str")
def show(date_str: str) -> None:
    """Print the current vault section for DATE."""
    date = _parse_date(date_str)
    section = read_daily_section(date)
    if section is None:
        click.echo(f"no vault section for {date.isoformat()}", err=True)
        sys.exit(2)
    click.echo(section)


@main.command("show-weekly")
@click.argument("week_str")
def show_weekly(week_str: str) -> None:
    """Print the current vault section for WEEK."""
    try:
        week_label = parse_week(week_str)
    except ValueError as exc:
        click.echo(f"error: {exc}", err=True)
        sys.exit(2)
    section = read_weekly_section(week_label)
    if section is None:
        click.echo(f"no vault section for {week_label}", err=True)
        sys.exit(2)
    click.echo(section)


# ─── reset / reset-weekly ────────────────────────────────────────────────────


@main.command()
@click.argument("date_str")
def reset(date_str: str) -> None:
    """Remove the vault-review section for DATE."""
    date = _parse_date(date_str)
    if remove_daily_section(date):
        click.echo(f"removed vault section for {date.isoformat()}", err=True)
    else:
        click.echo(f"no vault section to remove for {date.isoformat()}", err=True)


@main.command("reset-weekly")
@click.argument("week_str")
def reset_weekly(week_str: str) -> None:
    """Remove the vault-review weekly section for WEEK."""
    try:
        week_label = parse_week(week_str)
    except ValueError as exc:
        click.echo(f"error: {exc}", err=True)
        sys.exit(2)
    if remove_weekly_section(week_label):
        click.echo(f"removed vault section for {week_label}", err=True)
    else:
        click.echo(f"no vault section to remove for {week_label}", err=True)


if __name__ == "__main__":
    main()
