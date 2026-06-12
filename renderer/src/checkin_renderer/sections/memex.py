"""memex inbox section: a day's memex.captures window -> markdown.

Port of memex-review's render_dossier (memex-review/src/memex_review/dossier.py)
over PG rows instead of API Thoughts — same flat-chronological inbox framing,
same HH:MM / summary-or-first-line / tag-chip line shape. The one deliberate
divergence is the heading: `## memex — D — inbox` (the renderer's canonical
heading per DESIGN.md's bracket example) instead of `## memex-review — …`,
because the memex-review tool dissolves (design decision 1).

Pure function: no I/O.
"""

from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

from ..queries import CaptureRow


def _line_text(c: CaptureRow) -> str:
    """One-line summary for a capture.

    Prefer `summary` (LLM-enriched), fall back to the first non-empty line of
    `content` (the sync stores the feed's content_preview; the render takes
    only the first line of it, so the preview cap is irrelevant). Newlines are
    collapsed so the line is safe inside a markdown bullet.
    """
    raw = (c.summary or c.content or "").strip()
    if not raw:
        return "(empty)"
    first = next((ln.strip() for ln in raw.splitlines() if ln.strip()), raw.strip())
    return " ".join(first.split())


def _hhmm(c: CaptureRow, tz: ZoneInfo) -> str:
    return c.created_at.astimezone(tz).strftime("%H:%M")


def _tag_chips(c: CaptureRow) -> str:
    if not c.tags:
        return ""
    chips = " ".join(f"#{tag}" for tag in c.tags)
    return f" `[{chips}]`"


def render_memex_section(captures: list[CaptureRow], date: dt.date, tz: ZoneInfo) -> str:
    """Render the memex inbox section body (no trailing newline)."""
    items = sorted(captures, key=lambda c: c.created_at)
    count = len(items)
    out: list[str] = [
        f"## memex — {date.isoformat()} — inbox",
        "",
        f"_window: {date.isoformat()} — {count} capture{'s' if count != 1 else ''}_",
        "",
    ]
    if not items:
        out.append("_no captures in window_")
        return "\n".join(out)

    for c in items:
        out.append(f"- {_hhmm(c, tz)} — {_line_text(c)}{_tag_chips(c)}")
    return "\n".join(out)


__all__ = ["render_memex_section"]
