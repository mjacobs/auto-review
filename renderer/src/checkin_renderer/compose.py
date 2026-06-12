"""Section order, frontmatter, and bracket vs full assembly.

The ORDER BY is a literal list (closes auto-review-pfy): sections render in
today's reading order regardless of which producers have migrated. In bracket
mode the renderer is one more marker writer with a single contiguous
begin/end pair holding ALL renderer-owned sections; re-runs strip-and-replace
the explicit pair (not the fragile heading-to-close-marker span the siblings
use). Full mode — whole-file regeneration — is the step-D flip and is gated
off in Phase 1.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping

import frontmatter

# Fixed reading order; `projects` is a named no-op extension point for 8cw.
SECTION_ORDER: tuple[str, ...] = ("health", "vault", "memex", "agent", "projects")


def begin_marker(date: dt.date) -> str:
    return f"<!-- checkin-renderer:begin daily={date.isoformat()} -->"


def end_marker(date: dt.date, generated_at: dt.datetime) -> str:
    ts = generated_at.astimezone(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return f"<!-- checkin-renderer:end daily={date.isoformat()} generated_at={ts} -->"


def compose_bracket(
    date: dt.date,
    sections: Mapping[str, str | None],
    *,
    generated_at: dt.datetime,
) -> str:
    """Assemble the renderer's begin/end bracket for `date`.

    `sections` maps section name -> rendered markdown (or None to skip);
    assembly order comes from SECTION_ORDER, not the mapping. `generated_at`
    in the end marker is the only moving part between re-runs over the same
    rows (byte-stability is judged modulo that timestamp).
    """
    bodies = [
        sections[name].strip("\n")
        for name in SECTION_ORDER
        if sections.get(name) is not None
    ]
    parts = [begin_marker(date)]
    if bodies:
        parts.append("\n\n".join(bodies))
    parts.append(end_marker(date, generated_at))
    return "\n".join(parts)


def compose_full(date: dt.date, sections: Mapping[str, str | None]) -> str:
    """Whole-file regeneration — the step-D flip (RENDER_MODE=full).

    Stubbed by design in Phase 1: the flip happens only when no other writer
    remains, is announced, and is gated on user sign-off (DESIGN.md decision 2).
    """
    raise NotImplementedError(
        "RENDER_MODE=full is the step-D flip (Phase 4) and is not implemented yet; "
        "use bracket mode"
    )


def default_daily_post(date: dt.date) -> frontmatter.Post:
    """A fresh check-in note skeleton — frontmatter identical to today's
    convention (created/date/tags: [journal/checkin]) plus the title line."""
    return frontmatter.Post(
        content=f"# check-in — {date.isoformat()}\n",
        **{
            "created": date.isoformat(),
            "tags": ["journal/checkin"],
            "date": date.isoformat(),
        },
    )


__all__ = [
    "SECTION_ORDER",
    "begin_marker",
    "end_marker",
    "compose_bracket",
    "compose_full",
    "default_daily_post",
]
