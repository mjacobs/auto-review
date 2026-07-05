"""click-based CLI. See `agent-review --help`."""

from __future__ import annotations

import datetime as dt
import json
import sys
from dataclasses import dataclass

import click
from dateutil import parser as date_parser

from .config import get_settings
from .db import connect
from .digest import get_or_create_digest, get_or_create_digest_result
from .extract import extract_day, extract_session
from .runlog import record_best_effort, record_job_run
from .synth import persist_report, synthesize_day


@dataclass
class RunOutcome:
    """What one date's `_run_one` produced — aggregated into the job_runs row."""

    date: dt.date
    sessions: int        # in-scope sessions seen
    persisted: bool      # a daily_reports row was written
    cost_usd: float      # summed LLM cost (0.0 when nothing persisted)

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
@click.option("--dry-run", is_flag=True, help="Don't persist the report (no DB write, no job_runs row).")
@click.option("--no-vault", is_flag=True, hidden=True,
              help="Deprecated no-op: agent-review is always DB-only now "
                   "(ADR 002 / hg6.6). Kept so existing wrappers don't break.")
@click.option("--print", "do_print", is_flag=True, help="Print rendered section to stdout.")
@click.option("--force", is_flag=True, help="Force re-digest of all sessions for the date.")
def run(date_str: str, dry_run: bool, no_vault: bool, do_print: bool, force: bool) -> None:
    """Generate a daily report for DATE (default: today). DATE may be 'today',
    'yesterday', a date like '2026-05-14', or a range like
    '2026-05-10..2026-05-14' / 'last-week'. The report persists to
    agent_review.daily_reports; the check-in renderer reads that row and emits
    the note section (agent-review writes no files — hg6.6)."""
    dates = _parse_range(date_str)
    started_at = dt.datetime.now(dt.UTC)
    outcomes: list[RunOutcome] = []
    try:
        for date in dates:
            outcome = _run_one(date, dry_run=dry_run, do_print=do_print, force=force)
            if outcome is not None:
                outcomes.append(outcome)
    except Exception as exc:
        # Best-effort 'error' row so the doctor (auto-review-hg6.8) sees a
        # crash as a failed run, not a silent overdue. The original error
        # still propagates. Skipped under --dry-run (persists nothing).
        if not dry_run:
            record_best_effort(
                get_settings(),
                started_at=started_at,
                status="error",
                summary=_run_summary(dates, outcomes, error=f"{type(exc).__name__}: {exc}"),
                cost_usd=_total_cost(outcomes),
            )
        raise
    # --dry-run writes nothing (no job_runs row either); a normal run persists
    # the report and therefore records its run here. A quiet day with no
    # in-scope sessions still records 'ok' — the job ran.
    if not dry_run:
        record_job_run(
            get_settings(),
            started_at=started_at,
            status="ok",
            summary=_run_summary(dates, outcomes),
            cost_usd=_total_cost(outcomes),
        )


def _total_cost(outcomes: list[RunOutcome]) -> float | None:
    """Summed LLM cost across the invocation; None when nothing was persisted
    (keeps the job_runs.cost_usd column NULL rather than a misleading 0.0000)."""
    total = round(sum(o.cost_usd for o in outcomes), 4)
    return total if any(o.persisted for o in outcomes) else None


def _run_summary(
    dates: list[dt.date], outcomes: list[RunOutcome], *, error: str | None = None
) -> dict:
    """The ops.job_runs summary payload for a `run` invocation."""
    payload = {
        "dates": [d.isoformat() for d in dates],
        "reports": sum(1 for o in outcomes if o.persisted),
        "sessions": sum(o.sessions for o in outcomes),
        "model": get_settings().model_synth,
    }
    if error is not None:
        payload["error"] = error
    return payload


# Convenience aliases
@main.command()
@click.option("--dry-run", is_flag=True)
@click.option("--no-vault", is_flag=True, hidden=True)
@click.option("--print", "do_print", is_flag=True)
@click.option("--force", is_flag=True)
@click.pass_context
def today(ctx: click.Context, **kw) -> None:
    """Alias for `run today`."""
    ctx.invoke(run, date_str="today", **kw)


@main.command()
@click.option("--dry-run", is_flag=True)
@click.option("--no-vault", is_flag=True, hidden=True)
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
    do_print: bool,
    force: bool,
) -> RunOutcome | None:
    s = get_settings()
    click.echo(f"\n=== {date.isoformat()} ({s.tz_name}) ===", err=True)

    bundles = extract_day(date)
    if not bundles:
        click.echo("  no in-scope sessions; skipping.", err=True)
        return RunOutcome(date=date, sessions=0, persisted=False, cost_usd=0.0)
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
        return RunOutcome(date=date, sessions=len(bundles), persisted=False, cost_usd=0.0)

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
        click.echo("  --dry-run: not persisting.", err=True)
        return RunOutcome(date=date, sessions=len(bundles), persisted=False, cost_usd=0.0)

    persist_report(report)
    click.echo(f"  persisted to agent_review.daily_reports[{date.isoformat()}]", err=True)
    # agent-review writes no files: the check-in renderer reads this row and
    # emits the note section (hg6.6 — DB is the store, markdown is a projection).
    return RunOutcome(
        date=date, sessions=len(bundles), persisted=True, cost_usd=report.est_cost_usd
    )


# ─── show / reset ────────────────────────────────────────────────────────────


@main.command()
@click.argument("date_str")
def show(date_str: str) -> None:
    """Print the stored daily report for DATE."""
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


@main.command()
@click.argument("date_str")
def reset(date_str: str) -> None:
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


if __name__ == "__main__":
    main()
