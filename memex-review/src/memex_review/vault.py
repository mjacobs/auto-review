"""Vault writer with idempotent section markers.

Writes the rendered memex-review section into the day's check-in note with
marker-based replace-in-place semantics. Re-running for the same date
replaces the existing section, preserving frontmatter and any human edits
outside the marked block.

Marker format:
  <!-- memex-review:daily=YYYY-MM-DD generated_at=… -->

Section spans from a `## memex-review …` heading through the closing marker.

Daily-only by design — see DESIGN.md, "Out of scope (v1)".
"""

from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

import frontmatter

from .config import get_settings


def _daily_section_re(date: dt.date) -> re.Pattern[str]:
    """Match a full memex-review daily section for `date`."""
    return re.compile(
        r"## memex-review[^\n]*\n.*?<!-- memex-review:daily="
        + re.escape(date.isoformat())
        + r"[^\n]*-->\n?",
        re.DOTALL,
    )


def _default_daily_post(date: dt.date) -> frontmatter.Post:
    return frontmatter.Post(
        content=f"# check-in — {date.isoformat()}\n",
        **{
            "created": date.isoformat(),
            "tags": ["journal/checkin"],
            "date": date.isoformat(),
        },
    )


def _closing_marker(date: dt.date) -> str:
    now = dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return f"<!-- memex-review:daily={date.isoformat()} generated_at={now} -->"


def _checkin_path(date: dt.date) -> Path:
    return get_settings().checkins_dir / f"{date.isoformat()}.md"


def write_daily_section(date: dt.date, section_md: str) -> Path:
    """Append or replace the memex-review section in the day's check-in note.

    Creates the note (with default frontmatter) if it doesn't exist. Returns
    the path written.
    """
    s = get_settings()
    s.checkins_dir.mkdir(parents=True, exist_ok=True)
    note_path = _checkin_path(date)

    post = frontmatter.load(note_path) if note_path.exists() else _default_daily_post(date)

    full_section = section_md.rstrip() + "\n" + _closing_marker(date) + "\n"

    body = post.content or ""
    body = _daily_section_re(date).sub("", body)
    body = body.rstrip() + "\n\n" + full_section
    post.content = body

    note_path.write_text(frontmatter.dumps(post) + "\n", encoding="utf-8")
    return note_path


def read_daily_section(date: dt.date) -> str | None:
    """Return the current memex-review daily section for `date`, or None."""
    note_path = _checkin_path(date)
    if not note_path.exists():
        return None
    post = frontmatter.load(note_path)
    m = _daily_section_re(date).search(post.content or "")
    return m.group(0) if m else None


def remove_daily_section(date: dt.date) -> bool:
    """Remove the memex-review daily section from the note, if present.

    Returns True if a section was removed.
    """
    note_path = _checkin_path(date)
    if not note_path.exists():
        return False
    post = frontmatter.load(note_path)
    new_body, n = _daily_section_re(date).subn("", post.content or "")
    if n == 0:
        return False
    post.content = new_body.rstrip() + "\n"
    note_path.write_text(frontmatter.dumps(post) + "\n", encoding="utf-8")
    return True


__all__ = ["write_daily_section", "read_daily_section", "remove_daily_section"]
