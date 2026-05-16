"""Stage 4: vault writer.

Writes the rendered section to ~/vault/journal/checkins/YYYY-MM-DD.md.
Idempotent: re-running for the same date replaces the existing section
in-place using a comment marker, preserving any human edits to the file.
"""

from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

import frontmatter

from .config import get_settings


# Match a full agent-review section: from `## agent-review` through (and
# including) the closing `<!-- agent-review:report_date=YYYY-MM-DD ... -->`.
def _section_re(date: dt.date) -> re.Pattern[str]:
    return re.compile(
        r"## agent-review[^\n]*\n.*?<!-- agent-review:report_date="
        + re.escape(date.isoformat())
        + r"[^\n]*-->\n?",
        re.DOTALL,
    )


def _trailing_section_re(date: dt.date) -> re.Pattern[str]:
    """A second pass for any orphan section header for this date that didn't
    close with a marker (e.g. from an aborted run). Conservative: only matches
    a heading literally `## agent-review` followed by content up to the next
    `## ` heading or end of file."""
    return re.compile(
        r"## agent-review — "
        + re.escape(date.isoformat())
        + r"[^\n]*\n(?:.*?)(?=\n## |\Z)",
        re.DOTALL,
    )


def write_section(report_date: dt.date, section_md: str) -> Path:
    """Append or replace the agent-review section in the day's check-in note.
    Creates the note (with default frontmatter) if it doesn't exist. Returns
    the path written."""
    s = get_settings()
    s.checkins_dir.mkdir(parents=True, exist_ok=True)
    note_path = s.checkins_dir / f"{report_date.isoformat()}.md"

    if note_path.exists():
        post = frontmatter.load(note_path)
    else:
        post = frontmatter.Post(
            content=_default_body(report_date),
            **{
                "created": report_date.isoformat(),
                "tags": ["journal/checkin"],
                "date": report_date.isoformat(),
            },
        )

    body = post.content or ""
    body = _section_re(report_date).sub("", body)
    body = body.rstrip() + "\n\n" + section_md.rstrip() + "\n"
    post.content = body

    note_path.write_text(frontmatter.dumps(post) + "\n", encoding="utf-8")
    return note_path


def read_section(report_date: dt.date) -> str | None:
    """Return the current agent-review section for the date, or None."""
    s = get_settings()
    note_path = s.checkins_dir / f"{report_date.isoformat()}.md"
    if not note_path.exists():
        return None
    post = frontmatter.load(note_path)
    m = _section_re(report_date).search(post.content or "")
    return m.group(0) if m else None


def remove_section(report_date: dt.date) -> bool:
    """Remove the agent-review section from the day's note, if present.
    Returns True if a section was removed."""
    s = get_settings()
    note_path = s.checkins_dir / f"{report_date.isoformat()}.md"
    if not note_path.exists():
        return False
    post = frontmatter.load(note_path)
    new_body, n = _section_re(report_date).subn("", post.content or "")
    if n == 0:
        return False
    post.content = new_body.rstrip() + "\n"
    note_path.write_text(frontmatter.dumps(post) + "\n", encoding="utf-8")
    return True


def _default_body(report_date: dt.date) -> str:
    return f"# check-in — {report_date.isoformat()}\n"
