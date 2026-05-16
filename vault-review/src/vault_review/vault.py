"""Vault writer with idempotent section markers.

Writes rendered dossier sections to vault notes with marker-based
replace-in-place semantics. Re-running for the same date/week replaces the
existing section, preserving frontmatter and any human edits outside the
marked block.

Marker format:
  Daily:  <!-- vault-review:daily=YYYY-MM-DD generated_at=… -->
  Weekly: <!-- vault-review:weekly=YYYY-W## generated_at=… -->

Section spans from a `## vault-review …` heading through the closing marker.
"""

from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

import frontmatter

from .config import get_settings


# ─── regex helpers ────────────────────────────────────────────────────────────


def _daily_section_re(date: dt.date) -> re.Pattern[str]:
    """Match a full vault-review daily section for `date`."""
    return re.compile(
        r"## vault-review[^\n]*\n.*?<!-- vault-review:daily="
        + re.escape(date.isoformat())
        + r"[^\n]*-->\n?",
        re.DOTALL,
    )


def _weekly_section_re(week_label: str) -> re.Pattern[str]:
    """Match a full vault-review weekly section for `week_label` (e.g. '2026-W19')."""
    return re.compile(
        r"## vault-review[^\n]*\n.*?<!-- vault-review:weekly="
        + re.escape(week_label)
        + r"[^\n]*-->\n?",
        re.DOTALL,
    )


# ─── default frontmatter / body skeletons ────────────────────────────────────


def _default_daily_post(date: dt.date) -> frontmatter.Post:
    return frontmatter.Post(
        content=f"# check-in — {date.isoformat()}\n",
        **{
            "created": date.isoformat(),
            "tags": ["journal/checkin"],
            "date": date.isoformat(),
        },
    )


def _default_weekly_post(week_label: str) -> frontmatter.Post:
    """Bootstrap a weekly note with the standard Obsidian skeleton."""
    iso_year, iso_week = int(week_label[:4]), int(week_label[6:])
    monday = dt.date.fromisocalendar(iso_year, iso_week, 1)
    prev_iso = (monday - dt.timedelta(days=7)).isocalendar()
    next_iso = (monday + dt.timedelta(days=7)).isocalendar()
    prev_link = f"{prev_iso[0]}-W{prev_iso[1]:02d}"
    next_link = f"{next_iso[0]}-W{next_iso[1]:02d}"
    body = (
        f"# week of {monday.isoformat()}\n\n"
        f"<< [[{prev_link}]] | [[{next_link}]] >>\n\n"
        "## projects that moved forward\n\n"
        "## things I shipped or demoed\n\n"
        "## rabbit holes to drop\n\n"
        "## rabbit holes to double down on\n\n"
        "## what surprised me this week\n\n"
        "## plan for next week\n\n"
    )
    return frontmatter.Post(
        content=body,
        **{
            "created": dt.date.today().isoformat(),
            "tags": ["journal/weekly"],
        },
    )


# ─── marker builder ──────────────────────────────────────────────────────────


def _closing_marker(kind: str, label: str) -> str:
    now = dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return f"<!-- vault-review:{kind}={label} generated_at={now} -->"


# ─── daily write / read / remove ─────────────────────────────────────────────


def write_daily_section(date: dt.date, section_md: str) -> Path:
    """Append or replace the vault-review section in the day's check-in note.

    Creates the note (with default frontmatter) if it doesn't exist. Returns
    the path written.
    """
    s = get_settings()
    s.checkins_dir.mkdir(parents=True, exist_ok=True)
    note_path = s.checkins_dir / f"{date.isoformat()}.md"

    if note_path.exists():
        post = frontmatter.load(note_path)
    else:
        post = _default_daily_post(date)

    marker = _closing_marker("daily", date.isoformat())
    full_section = section_md.rstrip() + "\n" + marker + "\n"

    body = post.content or ""
    body = _daily_section_re(date).sub("", body)
    body = body.rstrip() + "\n\n" + full_section
    post.content = body

    note_path.write_text(frontmatter.dumps(post) + "\n", encoding="utf-8")
    return note_path


def read_daily_section(date: dt.date) -> str | None:
    """Return the current vault-review daily section for `date`, or None."""
    s = get_settings()
    note_path = s.checkins_dir / f"{date.isoformat()}.md"
    if not note_path.exists():
        return None
    post = frontmatter.load(note_path)
    m = _daily_section_re(date).search(post.content or "")
    return m.group(0) if m else None


def remove_daily_section(date: dt.date) -> bool:
    """Remove the vault-review daily section from the note, if present.

    Returns True if a section was removed.
    """
    s = get_settings()
    note_path = s.checkins_dir / f"{date.isoformat()}.md"
    if not note_path.exists():
        return False
    post = frontmatter.load(note_path)
    new_body, n = _daily_section_re(date).subn("", post.content or "")
    if n == 0:
        return False
    post.content = new_body.rstrip() + "\n"
    note_path.write_text(frontmatter.dumps(post) + "\n", encoding="utf-8")
    return True


# ─── weekly write / read / remove ────────────────────────────────────────────


def _week_note_path(week_label: str) -> Path:
    s = get_settings()
    return s.weekly_dir / f"{week_label}.md"


def write_weekly_section(week_label: str, section_md: str) -> Path:
    """Append or replace the vault-review section in the weekly note.

    Creates the note (with default skeleton frontmatter) if it doesn't exist.
    Returns the path written.
    """
    s = get_settings()
    s.weekly_dir.mkdir(parents=True, exist_ok=True)
    note_path = _week_note_path(week_label)

    if note_path.exists():
        post = frontmatter.load(note_path)
    else:
        post = _default_weekly_post(week_label)

    marker = _closing_marker("weekly", week_label)
    full_section = section_md.rstrip() + "\n" + marker + "\n"

    body = post.content or ""
    body = _weekly_section_re(week_label).sub("", body)
    body = body.rstrip() + "\n\n" + full_section
    post.content = body

    note_path.write_text(frontmatter.dumps(post) + "\n", encoding="utf-8")
    return note_path


def read_weekly_section(week_label: str) -> str | None:
    """Return the current vault-review weekly section for `week_label`, or None."""
    note_path = _week_note_path(week_label)
    if not note_path.exists():
        return None
    post = frontmatter.load(note_path)
    m = _weekly_section_re(week_label).search(post.content or "")
    return m.group(0) if m else None


def remove_weekly_section(week_label: str) -> bool:
    """Remove the vault-review weekly section from the note, if present.

    Returns True if a section was removed.
    """
    note_path = _week_note_path(week_label)
    if not note_path.exists():
        return False
    post = frontmatter.load(note_path)
    new_body, n = _weekly_section_re(week_label).subn("", post.content or "")
    if n == 0:
        return False
    post.content = new_body.rstrip() + "\n"
    note_path.write_text(frontmatter.dumps(post) + "\n", encoding="utf-8")
    return True
