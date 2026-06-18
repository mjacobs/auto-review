"""click-based CLI. See `memex-triage-cli --help`.

A terminal-native triage surface over the PG-owned `memex.capture_triage`
state (auto-review-hg6.9): the replacement for checking boxes in
`inbox/memex.md`. It reads the captures mirror and flips triage state — nothing
else (the `memex_triage` role's grants enforce that boundary). It never touches
the D1 feed and never writes the captures mirror.

Verbs:
  list     (default) numbered, seq-ordered rows for one state
           (--state untriaged|filed|discarded, default untriaged).
  file     SEQ...    set state -> 'filed'
  discard  SEQ...    set state -> 'discarded'
  reset    SEQ...    set state -> 'untriaged'

Each mutating verb takes the human-visible seq (or an id-prefix), resolves it
to a capture id, and runs the flip in one transaction, echoing `<seq> -> <state>`.
Bare `memex-triage-cli` runs `list` with defaults.
"""

from __future__ import annotations

import re
from zoneinfo import ZoneInfo

import click

from .config import get_settings
from .triage import Capture, UnknownCaptureError, list_inbox, set_states

_NON_TAG = re.compile(r"[^a-z0-9]+")


@click.group(invoke_without_command=True)
@click.version_option(package_name="memex-triage-cli")
@click.pass_context
def main(ctx: click.Context) -> None:
    """Triage memex captures held in Postgres (the inbox/memex.md replacement)."""
    if ctx.invoked_subcommand is None:
        ctx.invoke(list_)


@main.command(name="list")
@click.option(
    "--state",
    type=click.Choice(["untriaged", "filed", "discarded"]),
    default="untriaged",
    show_default=True,
    help="Which triage bucket to list.",
)
def list_(state: str) -> None:
    """List captures in STATE, numbered and seq-ordered."""
    tz = get_settings().tz
    rows = list_inbox(state)
    if not rows:
        click.echo(f"({state}: no captures)", err=True)
        return
    width = len(str(rows[-1].seq))
    for cap in rows:
        click.echo(render_line(cap, tz, width=width))


@main.command()
@click.argument("seqs", nargs=-1, required=True, metavar="SEQ...")
def file(seqs: tuple[str, ...]) -> None:
    """Mark each SEQ (or id-prefix) as filed."""
    _flip(seqs, "filed")


@main.command()
@click.argument("seqs", nargs=-1, required=True, metavar="SEQ...")
def discard(seqs: tuple[str, ...]) -> None:
    """Mark each SEQ (or id-prefix) as discarded."""
    _flip(seqs, "discarded")


@main.command()
@click.argument("seqs", nargs=-1, required=True, metavar="SEQ...")
def reset(seqs: tuple[str, ...]) -> None:
    """Return each SEQ (or id-prefix) to untriaged."""
    _flip(seqs, "untriaged")


def _flip(seqs: tuple[str, ...], state: str) -> None:
    try:
        resolved = set_states(seqs, state)
    except UnknownCaptureError as exc:
        raise click.ClickException(str(exc)) from exc
    for token, _capture_id in resolved:
        click.echo(f"{token} -> {state}")


def _normalize_tag(raw: str) -> str:
    """Kebab-case a tag into a valid single `#tag` (mirrors the inbox render)."""
    s = _NON_TAG.sub("-", raw.lower().lstrip("#"))
    return re.sub(r"-+", "-", s).strip("-")


def _tag_chips(cap: Capture) -> str:
    chips = (_normalize_tag(tag) for tag in cap.tags)
    return "".join(f" #{c}" for c in chips if c)


def _label(cap: Capture) -> str:
    """The summary, else the first non-empty content line; whitespace collapsed."""
    raw = (cap.summary or cap.content or "").strip()
    if not raw:
        return "(empty)"
    first = next((ln.strip() for ln in raw.splitlines() if ln.strip()), raw)
    return " ".join(first.split())


def render_line(cap: Capture, tz: ZoneInfo, *, width: int = 0) -> str:
    """One human-scannable inbox row: seq, HH:MM, id-prefix, label, #tag chips."""
    when = cap.created_at.astimezone(tz).strftime("%H:%M")
    prefix = cap.id.replace("-", "")[:8]
    return f"{cap.seq:>{width}}  {when}  {prefix}  {_label(cap)}{_tag_chips(cap)}"


if __name__ == "__main__":
    main()
