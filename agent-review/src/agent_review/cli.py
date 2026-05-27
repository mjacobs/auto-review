"""click-based CLI. See `agent-review --help`."""

from __future__ import annotations

import datetime as dt
import json
import sys

import click
from dateutil import parser as date_parser

from .config import get_settings
from .db import connect
from .digest import get_or_create_digest, get_or_create_digest_result
from .extract import extract_day, extract_session
from .synth import persist_report, synthesize_day
from .vault import read_section, remove_section, write_section

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
    """agent-review — daily narrative reports of agent activity."""


# ─── extract (stage 1 only) ──────────────────────────────────────────────────


@main.command()
@click.argument("date_str")
@click.option("--print", "do_print", is_flag=True, help="Print bundles as JSON.")
def extract(date_str: str, do_print: bool) -> None:
    """Run stage 1 only: pull in-scope sessions for DATE."""
    date = _parse_date(date_str)
    bundles = extract_day(date)
    click.echo(
        f"[{date.isoformat()}] {len(bundles)} in-scope sessions",
        err=True,
    )
    for b in bundles:
        click.echo(
            f"  {b.started_at.astimezone(get_settings().tz).strftime('%H:%M')}  "
            f"{b.agent:<10}  {b.project:<20}  msgs={b.message_count:<4}  "
            f"tools={b.tool_summary.total_calls:<4}  {b.outcome}  "
            f"{b.session_id}",
            err=True,
        )
    if do_print:
        out = [b.to_dict() for b in bundles]
        click.echo(json.dumps(out, indent=2, default=str))


# ─── digest (stage 2 only, single session) ──────────────────────────────────


@main.command()
@click.argument("session_id")
@click.option("--force", is_flag=True, help="Bypass cache, re-run digest.")
@click.option("--print", "do_print", is_flag=True, help="Print digest JSON.")
def digest(session_id: str, force: bool, do_print: bool) -> None:
    """Run stage 2 only: digest a single session."""
    bundle = extract_session(session_id)
    if bundle is None:
        click.echo(f"session not found: {session_id}", err=True)
        sys.exit(2)
    d = get_or_create_digest(bundle, force=force)
    click.echo(f"[{session_id}] outcome={d.outcome}  confidence={d.confidence}", err=True)
    click.echo(f"  summary: {d.summary}", err=True)
    if do_print:
        click.echo(json.dumps(d.model_dump(), indent=2))


# ─── full pipeline (today / yesterday / DATE / RANGE) ───────────────────────


@main.command()
@click.argument("date_str", default="today")
@click.option("--dry-run", is_flag=True, help="Don't write to vault, don't persist report.")
@click.option("--no-vault", is_flag=True, help="Persist report to DB but don't write to vault.")
@click.option("--print", "do_print", is_flag=True, help="Print rendered section to stdout.")
@click.option("--force", is_flag=True, help="Force re-digest of all sessions for the date.")
def run(date_str: str, dry_run: bool, no_vault: bool, do_print: bool, force: bool) -> None:
    """Generate a daily report for DATE (default: today). DATE may be 'today',
    'yesterday', a date like '2026-05-14', or a range like
    '2026-05-10..2026-05-14' / 'last-week'."""
    dates = _parse_range(date_str)
    for date in dates:
        _run_one(date, dry_run=dry_run, no_vault=no_vault, do_print=do_print, force=force)


# Convenience aliases
@main.command()
@click.option("--dry-run", is_flag=True)
@click.option("--no-vault", is_flag=True)
@click.option("--print", "do_print", is_flag=True)
@click.option("--force", is_flag=True)
@click.pass_context
def today(ctx: click.Context, **kw) -> None:
    """Alias for `run today`."""
    ctx.invoke(run, date_str="today", **kw)


@main.command()
@click.option("--dry-run", is_flag=True)
@click.option("--no-vault", is_flag=True)
@click.option("--print", "do_print", is_flag=True)
@click.option("--force", is_flag=True)
@click.pass_context
def yesterday(ctx: click.Context, **kw) -> None:
    """Alias for `run yesterday`."""
    ctx.invoke(run, date_str="yesterday", **kw)


def _run_one(
    date: dt.date,
    *,
    dry_run: bool,
    no_vault: bool,
    do_print: bool,
    force: bool,
) -> None:
    s = get_settings()
    click.echo(f"\n=== {date.isoformat()} ({s.tz_name}) ===", err=True)

    bundles = extract_day(date)
    if not bundles:
        click.echo("  no in-scope sessions; skipping.", err=True)
        return
    click.echo(f"  {len(bundles)} in-scope sessions", err=True)

    pairs: list[tuple] = []
    digest_usages: list[dict[str, int]] = []
    failures: list[tuple[str, str]] = []
    for b in bundles:
        try:
            d, usage, fresh = get_or_create_digest_result(
                b,
                force=force,
                persist=not dry_run,
            )
        except Exception as exc:
            failures.append((b.session_id, f"{type(exc).__name__}: {exc}"))
            click.echo(
                f"    SKIPPED {b.session_id[:24]}…  {type(exc).__name__}: {exc}",
                err=True,
            )
            continue
        if dry_run or fresh:
            digest_usages.append(usage)
        pairs.append((b, d))
        click.echo(
            f"    digested {b.session_id[:24]}…  outcome={d.outcome}",
            err=True,
        )

    if failures:
        click.echo(
            f"  {len(failures)} session(s) failed to digest; continuing without them.",
            err=True,
        )
    if not pairs:
        click.echo("  no successful digests; aborting day.", err=True)
        return

    click.echo("  synthesizing daily narrative…", err=True)
    report = synthesize_day(
        date,
        pairs,
        digest_usages=digest_usages if dry_run else None,
    )
    click.echo(
        f"  cost: digest=${report.stats['est_digest_cost_usd']:.4f}  "
        f"synth=${report.stats['est_synth_cost_usd']:.4f}  "
        f"total=${report.est_cost_usd:.4f}",
        err=True,
    )

    if do_print:
        click.echo(report.section_md)

    if dry_run:
        click.echo("  --dry-run: not persisting, not writing vault.", err=True)
        return

    persist_report(report)
    click.echo(f"  persisted to agent_review.daily_reports[{date.isoformat()}]", err=True)

    if no_vault:
        click.echo("  --no-vault: skipping vault write.", err=True)
        return

    path = write_section(date, report.section_md)
    click.echo(f"  wrote section → {path}", err=True)


# ─── show / reset ────────────────────────────────────────────────────────────


@main.command()
@click.argument("date_str")
def show(date_str: str) -> None:
    """Print the stored daily report (and the vault section) for DATE."""
    date = _parse_date(date_str)
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT report_date, generated_at, model, narrative_md, stats, "
            "       est_cost_usd, sessions_included "
            "  FROM agent_review.daily_reports WHERE report_date = %s",
            (date,),
        )
        row = cur.fetchone()
    if not row:
        click.echo(f"no stored report for {date.isoformat()}", err=True)
        sys.exit(2)
    click.echo(f"--- agent_review.daily_reports[{date.isoformat()}] ---")
    click.echo(f"generated_at: {row['generated_at']}")
    click.echo(f"model:        {row['model']}")
    click.echo(f"sessions:     {len(row['sessions_included'])}")
    click.echo(f"est_cost:     ${row['est_cost_usd']}")
    click.echo("--- section ---")
    click.echo(row["narrative_md"])
    section = read_section(date)
    if section:
        click.echo("--- vault current ---")
        click.echo(section)


@main.command()
@click.argument("date_str")
@click.option("--from-vault/--no-from-vault", default=True,
              help="Also remove the section from the vault note.")
def reset(date_str: str, from_vault: bool) -> None:
    """Delete cached digests + report for DATE so the next run re-does work."""
    date = _parse_date(date_str)
    bundles = extract_day(date)  # to learn the session ids in scope
    ids = [b.session_id for b in bundles]
    with connect() as conn, conn.cursor() as cur:
        if ids:
            cur.execute(
                "DELETE FROM agent_review.session_digests WHERE session_id = ANY(%s)",
                (ids,),
            )
            click.echo(f"deleted {cur.rowcount} cached digests", err=True)
        cur.execute(
            "DELETE FROM agent_review.daily_reports WHERE report_date = %s",
            (date,),
        )
        click.echo(f"deleted {cur.rowcount} report row", err=True)
        conn.commit()
    if from_vault:
        if remove_section(date):
            click.echo("removed vault section", err=True)
        else:
            click.echo("no vault section to remove", err=True)


if __name__ == "__main__":
    main()
