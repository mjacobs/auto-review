"""click-based CLI. See `memex-sync --help`.

Verbs:
  sync    (default) pull new captures from the change feed into memex.captures,
          seed triage rows, advance the watermark, record an ops.job_runs row.
  status  show the watermark vs the server head + mirror row counts.

Bare `memex-sync` runs `sync` with defaults; flags need the explicit verb
(`memex-sync sync --dry-run`).
"""

from __future__ import annotations

import click

from .client import Thought
from .config import get_settings
from .sync import SyncResult, run_sync, status_snapshot


@click.group(invoke_without_command=True)
@click.version_option(package_name="memex-sync")
@click.pass_context
def main(ctx: click.Context) -> None:
    """Sync cf-memex captures into the Postgres memex schema (canonical store)."""
    if ctx.invoked_subcommand is None:
        ctx.invoke(sync)


@main.command()
@click.option(
    "--since",
    type=click.IntRange(min=0),
    default=None,
    help="Walk the feed from this seq instead of the stored watermark "
    "(re-delivery is safe: upserts dedupe by capture id). The watermark "
    "advances to at least this value afterwards.",
)
@click.option("--dry-run", is_flag=True, help="Fetch and report only; write nothing (no job_runs row either).")
@click.option("--print", "do_print", is_flag=True, help="Print one line per fetched capture.")
def sync(since: int | None, dry_run: bool, do_print: bool) -> None:
    """Pull captures newer than the watermark into Postgres, then advance it.

    First run (no memex.sync_state row) backfills the full history from seq 0
    — the canonical store wants everything, unlike the triage inbox. Use
    `--since <seq>` to start elsewhere (e.g. the current head to skip history).
    """
    s = get_settings()
    result = run_sync(s, since=since, dry_run=dry_run)

    if do_print:
        for t in result.thoughts:
            click.echo(render_line(t))

    _echo_result(result)


def _echo_result(r: SyncResult) -> None:
    before = r.watermark_before if r.watermark_before is not None else "unset"
    if r.bootstrapped:
        click.echo(
            f"bootstrap: no sync_state row for {r.consumer!r}; walked feed from seq {r.since}",
            err=True,
        )

    if r.dry_run:
        if r.fetched == 0:
            click.echo(f"--dry-run: up to date (watermark {before}); nothing to write.", err=True)
        else:
            would = max(t.seq for t in r.thoughts)
            click.echo(
                f"--dry-run: would upsert {r.fetched} capture(s) and advance "
                f"watermark {before} -> {would} (no job_runs row).",
                err=True,
            )
        return

    if r.fetched == 0:
        click.echo(
            f"up to date (watermark {before}); nothing new. job_runs row recorded.",
            err=True,
        )
        return
    click.echo(
        f"upserted {r.upserted} capture(s), seeded {r.triage_seeded} triage row(s); "
        f"watermark {before} -> {r.watermark_after}. job_runs row recorded.",
        err=True,
    )


@main.command()
def status() -> None:
    """Show watermark vs server head and mirror row counts."""
    s = get_settings()
    snap = status_snapshot(s)

    click.echo(f"consumer:    {snap.consumer}")
    click.echo(f"server head: seq {snap.server_head}")
    if snap.watermark is None:
        click.echo("watermark:   unset (next sync backfills the full history from seq 0)")
    else:
        behind = max(snap.server_head - snap.watermark, 0)
        click.echo(f"watermark:   seq {snap.watermark} (behind head by <= {behind} seq)")
    click.echo(f"captures:    {snap.captures} row(s) mirrored")
    click.echo(f"untriaged:   {snap.untriaged} row(s)")


def render_line(t: Thought) -> str:
    """One human-scannable line per capture, for --print."""
    tags = " ".join(f"#{tag}" for tag in t.tags)
    text = (t.summary or t.content or "").strip().splitlines()
    first = text[0] if text else ""
    return f"seq {t.seq}  {t.created_at:%Y-%m-%d %H:%M}  {t.id}  {first}" + (
        f"  {tags}" if tags else ""
    )


if __name__ == "__main__":
    main()
