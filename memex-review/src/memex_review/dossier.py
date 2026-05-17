"""Render a flat-chronological inbox view of cf-memex captures.

Pure function: takes a list of `Thought` plus framing info, returns a
markdown string. No I/O.

The output is framed as an *inbox* (for downstream triage), not a topical
recap. See DESIGN.md and project memory `project-memex-review-inbox-framing`
for the reasoning.
"""

from __future__ import annotations

from zoneinfo import ZoneInfo

from .client import Thought


def _line_text(t: Thought) -> str:
    """One-line summary for a thought.

    Prefer `summary` (LLM-enriched), fall back to the first non-empty line
    of `content_preview`. Newlines are collapsed so the line is safe inside
    a markdown bullet.
    """
    raw = (t.summary or t.content_preview or "").strip()
    if not raw:
        return "(empty)"
    first = next((ln.strip() for ln in raw.splitlines() if ln.strip()), raw.strip())
    return " ".join(first.split())


def _hhmm(t: Thought, tz: ZoneInfo) -> str:
    return t.created_at.astimezone(tz).strftime("%H:%M")


def _tag_chips(t: Thought) -> str:
    if not t.tags:
        return ""
    chips = " ".join(f"#{tag}" for tag in t.tags)
    return f" `[{chips}]`"


def render_dossier(
    thoughts: list[Thought],
    window_label: str,
    heading: str,
    tz: ZoneInfo,
) -> str:
    """Render the markdown body of a memex-review inbox section.

    The closing HTML marker is appended by the vault writer, not here.

    Args:
        thoughts: Captures to surface, in any order (renderer sorts ascending).
        window_label: Human-readable window string (e.g. "2026-05-14").
        heading: Section heading text (e.g. "memex-review — 2026-05-14 — inbox").
        tz: Local timezone for HH:MM stamps.
    """
    items = sorted(thoughts, key=lambda t: t.created_at_ms)
    count = len(items)
    out: list[str] = [
        f"## {heading}",
        "",
        f"_window: {window_label} — {count} capture{'s' if count != 1 else ''}_",
        "",
    ]
    if not items:
        out += ["_no captures in window_", ""]
        return "\n".join(out)

    for t in items:
        out.append(f"- {_hhmm(t, tz)} — {_line_text(t)}{_tag_chips(t)}")
    out.append("")
    return "\n".join(out)


__all__ = ["render_dossier"]
