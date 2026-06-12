"""Note writers: bracket strip-and-replace (transition) + whole-file (step D).

Bracket semantics (DESIGN.md decision 2): load the existing note (or the
default skeleton), strip any existing `checkin-renderer:begin/end daily=D`
span, append the new bracket, write once. Sibling markers and human edits
outside the bracket survive. The explicit begin/end pair — not a
heading-to-close-marker span — is what makes the strip safe.

Weekly/monthly note creation with human skeletons lands with Phases 3/4.
"""

from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

import frontmatter

from .compose import default_daily_post
from .config import Settings, get_settings


def _bracket_re(date: dt.date) -> re.Pattern[str]:
    """Match a full renderer bracket for `date`, begin marker through end marker."""
    d = re.escape(date.isoformat())
    return re.compile(
        rf"<!-- checkin-renderer:begin daily={d} -->"
        rf".*?"
        rf"<!-- checkin-renderer:end daily={d}[^\n]*-->\n?",
        re.DOTALL,
    )


def write_daily_bracket(
    date: dt.date,
    bracket_md: str,
    *,
    settings: Settings | None = None,
) -> Path:
    """Append or replace the renderer bracket in the day's check-in note.

    Creates the note (with default frontmatter) if it doesn't exist. Returns
    the path written.
    """
    s = settings or get_settings()
    note_path = s.checkin_path(date)
    note_path.parent.mkdir(parents=True, exist_ok=True)

    post = frontmatter.load(note_path) if note_path.exists() else default_daily_post(date)

    body = post.content or ""
    body = _bracket_re(date).sub("", body)
    body = body.rstrip() + "\n\n" + bracket_md.strip("\n") + "\n"
    post.content = body

    note_path.write_text(frontmatter.dumps(post) + "\n", encoding="utf-8")
    return note_path


def read_daily_bracket(date: dt.date, *, settings: Settings | None = None) -> str | None:
    """Return the current renderer bracket for `date`, or None."""
    s = settings or get_settings()
    note_path = s.checkin_path(date)
    if not note_path.exists():
        return None
    post = frontmatter.load(note_path)
    m = _bracket_re(date).search(post.content or "")
    return m.group(0) if m else None


def read_note(date: dt.date, *, settings: Settings | None = None) -> str | None:
    """Return the raw note text for `date`, or None when absent."""
    s = settings or get_settings()
    note_path = s.checkin_path(date)
    if not note_path.exists():
        return None
    return note_path.read_text(encoding="utf-8")


def write_full(date: dt.date, note_md: str, *, settings: Settings | None = None) -> Path:
    """Whole-file writer for RENDER_MODE=full — the step-D flip.

    Stubbed by design in Phase 1 (gated, announced; see compose.compose_full).
    """
    raise NotImplementedError(
        "RENDER_MODE=full is the step-D flip (Phase 4) and is not implemented yet; "
        "use bracket mode"
    )


__all__ = ["write_daily_bracket", "read_daily_bracket", "read_note", "write_full"]
