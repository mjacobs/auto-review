"""click-based CLI. See `memex-triage --help`.

Verbs:
  sync    poll the change feed, append new captures to the inbox, advance the
          watermark. Bootstraps "at head" on first run. (the cron/timer target)
  status  show the watermark, server head, pending count, inbox size.
  init    create the inbox note at a chosen watermark (refuses if it exists).
"""

from __future__ import annotations

import sys

import click

from . import inbox
from .client import fetch_since, server_head
from .config import get_settings


@click.group()
@click.version_option(package_name="memex-triage")
def main() -> None:
    """Exactly-once delivery of cf-memex captures into the Obsidian triage inbox."""


@main.command()
@click.option("--dry-run", is_flag=True, help="Don't write to the vault.")
@click.option("--print", "do_print", is_flag=True, help="Print the lines (to be) appended.")
def sync(dry_run: bool, do_print: bool) -> None:
    """Append captures newer than the watermark to the inbox, then advance it.

    First run (no watermark) bootstraps at the current server head and delivers
    nothing — only captures created *after* bootstrap flow into the inbox.
    """
    s = get_settings()
    last_seq = inbox.load_last_seq(s)

    if last_seq is None:
        head = server_head(settings=s)
        if dry_run:
            click.echo(f"would bootstrap inbox at head (last_seq={head}); 0 delivered", err=True)
            return
        path = inbox.init_inbox(head, settings=s)
        click.echo(f"bootstrapped inbox at head (last_seq={head}) → {path}", err=True)
        click.echo("  no captures delivered; run again as new captures arrive.", err=True)
        return

    thoughts = fetch_since(last_seq, settings=s)
    if do_print:
        for t in thoughts:
            click.echo(inbox.render_line(t, s.tz))

    if not thoughts:
        click.echo(f"up to date (last_seq={last_seq}); nothing new.", err=True)
        return

    if dry_run:
        click.echo(
            f"--dry-run: would append {len(thoughts)} capture(s), "
            f"advance last_seq {last_seq} → {thoughts[-1].seq}",
            err=True,
        )
        return

    n = inbox.append_thoughts(thoughts, settings=s)
    new_seq = inbox.load_last_seq(s)
    click.echo(
        f"appended {n} capture(s) → {s.inbox_file}; last_seq {last_seq} → {new_seq}",
        err=True,
    )


@main.command()
def status() -> None:
    """Show watermark, server head, pending count, and inbox size."""
    s = get_settings()
    last_seq = inbox.load_last_seq(s)
    head = server_head(settings=s)
    lines = inbox.count_task_lines(s)

    click.echo(f"inbox:      {s.inbox_file}")
    click.echo(f"task lines: {lines}")
    click.echo(f"server head: seq {head}")
    if last_seq is None:
        click.echo("watermark:  unset (run `memex-triage sync` to bootstrap at head)")
        return
    pending = len(fetch_since(last_seq, settings=s))
    click.echo(f"watermark:  seq {last_seq}")
    click.echo(f"pending:    {pending} capture(s) with seq > {last_seq}")


@main.command()
@click.option(
    "--backfill",
    "backfill",
    default=None,
    help="Bootstrap at this seq instead of head (e.g. 0 to deliver the whole corpus).",
)
def init(backfill: str | None) -> None:
    """Create the inbox note at a chosen watermark. Refuses if it already exists."""
    s = get_settings()

    if backfill is not None:
        try:
            seq = int(backfill)
        except ValueError:
            click.echo(f"--backfill must be an integer seq, got {backfill!r}", err=True)
            sys.exit(2)
        if seq < 0:
            click.echo("--backfill seq must be >= 0", err=True)
            sys.exit(2)
    else:
        seq = server_head(settings=s)

    try:
        path = inbox.init_inbox(seq, settings=s)
    except FileExistsError:
        click.echo(
            f"inbox already exists at {s.inbox_file}; refusing to clobber. "
            "Edit its `last_seq` by hand to re-deliver.",
            err=True,
        )
        sys.exit(2)
    click.echo(f"initialized inbox at last_seq={seq} → {path}", err=True)


if __name__ == "__main__":
    main()
