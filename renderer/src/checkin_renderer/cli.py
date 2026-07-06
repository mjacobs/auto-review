"""click-based CLI. See `checkin-renderer --help`.

Verbs (DESIGN.md "CLI shape"):
  run [DATE|RANGE]   render the daily bracket (default: yesterday, the cron target)
  run-weekly         Phase 3 stub (step C, with hg6.7)
  run-monthly        Phase 4 stub (auto-review-2l1)
  show DATE          print the current bracket (or whole note) for DATE
  sections DATE      per-section row availability (debug: what would render)

The renderer is date-driven and stateless — no watermark, no cursor, no
`reset` verb: regeneration *is* the reset.
"""

from __future__ import annotations

import datetime as dt
import sys
import traceback

import click
from dateutil import parser as date_parser

from . import db, note, queries
from .compose import compose_bracket
from .config import Settings, get_settings
from .runlog import record_best_effort, record_job_run
from .sections.agent import is_legacy_row, render_agent_section
from .sections.health import render_health_section
from .sections.memex import render_memex_section
from .sections.projects import render_projects_section
from .sections.vault import render_vault_section

# ── date plumbing ─────────────────────────────────────────────────────────────


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
    if ".." in s:
        a, b = s.split("..", 1)
        start = _parse_date(a)
        end = _parse_date(b)
        if end < start:
            start, end = end, start
        days = (end - start).days
        return [start + dt.timedelta(days=i) for i in range(days + 1)]
    return [_parse_date(s)]


def _day_window(date: dt.date, s: Settings) -> tuple[dt.datetime, dt.datetime]:
    """[D 00:00, D+1 00:00) local — same as memex-review's collect_for_date."""
    start = dt.datetime.combine(date, dt.time.min, tzinfo=s.tz)
    return start, start + dt.timedelta(days=1)


# ── verbs ─────────────────────────────────────────────────────────────────────


@click.group()
@click.version_option(package_name="checkin-renderer")
def main() -> None:
    """Render the daily check-in note as a projection of the Postgres schemas."""


@main.command()
@click.argument("date_str", default="yesterday")
@click.option("--dry-run", is_flag=True, help="Render only; no note write, no job_runs row.")
@click.option("--print", "do_print", is_flag=True, help="Print the rendered bracket to stdout.")
@click.option(
    "--mode",
    type=click.Choice(["bracket", "full"]),
    default=None,
    help="Override RENDER_MODE for this run (testing the step-D flip).",
)
def run(date_str: str, dry_run: bool, do_print: bool, mode: str | None) -> None:
    """Render the check-in bracket for DATE (default: yesterday).

    DATE may be 'today', 'yesterday', '2026-06-10', or a range like
    '2026-06-01..2026-06-10'.
    """
    for date in _parse_range(date_str):
        _run_one(date, mode=mode, dry_run=dry_run, do_print=do_print)


def _run_one(date: dt.date, *, mode: str | None, dry_run: bool, do_print: bool) -> None:
    s = get_settings()
    mode = mode or s.render_mode
    if mode != "bracket":
        raise click.ClickException(
            "RENDER_MODE=full is the step-D flip (Phase 4) and is not implemented yet"
        )

    started_at = dt.datetime.now(tz=dt.UTC)
    click.echo(f"\n=== {date.isoformat()} ({s.tz_name}, mode={mode}) ===", err=True)

    try:
        sections, counts = _render_sections(date, s)
        bracket = compose_bracket(date, sections, generated_at=dt.datetime.now(tz=dt.UTC))

        if do_print:
            click.echo(bracket)

        if dry_run:
            click.echo("  --dry-run: no note write, no job_runs row.", err=True)
            return

        path = note.write_daily_bracket(date, bracket, settings=s)
    except Exception as exc:
        if not dry_run:
            record_best_effort(
                s,
                started_at=started_at,
                status="error",
                summary={
                    "date": date.isoformat(),
                    "mode": mode,
                    "error": f"{type(exc).__name__}: {exc}",
                    "trace": traceback.format_exc(limit=5),
                },
            )
        raise

    record_job_run(
        s,
        started_at=started_at,
        status="ok",
        summary={
            "date": date.isoformat(),
            "mode": mode,
            "sections": counts,
            "note_path": str(path),
        },
    )
    click.echo(f"  wrote bracket → {path}; job_runs row recorded.", err=True)


def _render_sections(
    date: dt.date, s: Settings
) -> tuple[dict[str, str | None], dict[str, dict]]:
    """Query each section's rows and render — fixed order lives in compose."""
    start, end = _day_window(date, s)
    with db.connect() as conn:
        captures = queries.fetch_memex_captures(conn, start, end)
        report = queries.fetch_agent_report(conn, date)
        vault_digest = queries.fetch_vault_digest(conn, date)

    sections: dict[str, str | None] = {
        "health": render_health_section(date),
        "vault": render_vault_section(vault_digest, date),
        "memex": render_memex_section(captures, date, s.tz),
        "agent": render_agent_section(report, date),
        "projects": render_projects_section(date),
    }
    counts = {
        "vault": {"row": vault_digest is not None,
                  "events": len(vault_digest.events) if vault_digest else 0},
        "memex": {"captures": len(captures)},
        "agent": {
            "row": report is not None,
            "legacy": report is not None and is_legacy_row(report.narrative_md),
        },
    }
    return sections, counts


@main.command(name="run-weekly")
@click.argument("week", default="last-week")
def run_weekly(week: str) -> None:
    """Render the weekly note's machine appendix (Phase 3 — not yet built)."""
    raise click.ClickException(
        "run-weekly lands in Phase 3 (step C, with hg6.7's weekly_digests rows) — see DESIGN.md"
    )


@main.command(name="run-monthly")
@click.argument("month", default="last-month")
def run_monthly(month: str) -> None:
    """Render the monthly rollup note (Phase 4 / auto-review-2l1 — not yet built)."""
    raise click.ClickException(
        "run-monthly lands in Phase 4 (with hg6.8/full job_runs coverage) — see DESIGN.md"
    )


@main.command()
@click.argument("date_str")
def show(date_str: str) -> None:
    """Print the current renderer bracket (or the whole note) for DATE."""
    date = _parse_date(date_str)
    s = get_settings()
    bracket = note.read_daily_bracket(date, settings=s)
    if bracket is not None:
        click.echo(bracket.rstrip("\n"))
        return
    text = note.read_note(date, settings=s)
    if text is None:
        click.echo(f"no check-in note for {date.isoformat()}", err=True)
        sys.exit(2)
    click.echo(f"(no renderer bracket in {date.isoformat()}'s note; printing whole note)", err=True)
    click.echo(text.rstrip("\n"))


@main.command(name="sections")
@click.argument("date_str")
def sections_cmd(date_str: str) -> None:
    """Per-section row availability for DATE (debug: what would render)."""
    date = _parse_date(date_str)
    s = get_settings()
    start, end = _day_window(date, s)
    with db.connect() as conn:
        captures = queries.fetch_memex_captures(conn, start, end)
        report = queries.fetch_agent_report(conn, date)
        vault_digest = queries.fetch_vault_digest(conn, date)

    click.echo(f"sections for {date.isoformat()} ({s.tz_name}):")
    click.echo("  health:   — (Phase 4 / step D; the doctor still owns the health section)")
    if vault_digest is None:
        click.echo("  vault:    NO daily_digests row — placeholder would render")
    else:
        click.echo(f"  vault:    row present ({len(vault_digest.events)} event(s))")
    click.echo(f"  memex:    {len(captures)} capture(s) in window")
    if report is None:
        click.echo("  agent:    NO daily_reports row — placeholder would render")
    elif is_legacy_row(report.narrative_md):
        click.echo("  agent:    row present (legacy full-section format; will normalize)")
    else:
        click.echo("  agent:    row present (canonical narrative)")
    click.echo("  projects: — (named extension point; no views until 8cw)")


if __name__ == "__main__":
    main()
