"""Append-only inbox writer with the delivery watermark in frontmatter.

The inbox note (`inbox/memex.md`) is the single triage surface. This module
owns exactly two things in it: appending task lines for new captures, and the
`last_seq` frontmatter property. Everything else in the body is the human's —
we never sort, dedupe, or rewrite it.

Appending the lines and advancing `last_seq` is a single atomic file write
(render → temp file → os.replace), so a crash either commits the whole batch or
none of it; there is no half-state where the watermark moved past un-appended
lines. See DESIGN.md.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import os
import re
import tempfile
from pathlib import Path
from zoneinfo import ZoneInfo

import frontmatter

from .client import Thought
from .config import Settings, get_settings

_HEADER = (
    "# inbox — memex\n\n"
    "Captures awaiting triage. Delete a line once it's filed. "
    "The tool only appends below and owns the `last_seq` property.\n"
)


def _line_text(t: Thought) -> str:
    """One-line label: prefer the LLM summary, else the first non-empty
    content line, with internal whitespace collapsed so it's bullet-safe."""
    raw = (t.summary or t.content_preview or "").strip()
    if not raw:
        return "(empty)"
    first = next((ln.strip() for ln in raw.splitlines() if ln.strip()), raw.strip())
    return " ".join(first.split())


def _anchor(t: Thought) -> str:
    """Stable Obsidian block ref + source backlink: ^mx-<first 8 hex of id>."""
    return f"^mx-{t.id.replace('-', '')[:8]}"


_NON_TAG = re.compile(r"[^a-z0-9]+")


def _normalize_tag(raw: str) -> str:
    """Kebab-case a tag so it's a valid single Obsidian `#tag`.

    Mirrors serverless-memex enrichment.ts normalizeTag: lowercase, drop a
    leading '#', map non-alphanumerics to '-', collapse/trim hyphens. Older
    captures carry un-normalized tags (e.g. 'cash investment'), and a space
    would otherwise terminate the tag and leak text into the line.
    """
    s = _NON_TAG.sub("-", raw.lower().lstrip("#"))
    return re.sub(r"-+", "-", s).strip("-")


def _tag_chips(t: Thought) -> str:
    chips = (_normalize_tag(tag) for tag in t.tags)
    return "".join(f" `#{c}`" for c in chips if c)


def render_line(t: Thought, tz: ZoneInfo) -> str:
    """A single inbox task line for one capture."""
    when = t.created_at.astimezone(tz).strftime("%m-%d %H:%M")
    return f"- [ ] {when} — {_line_text(t)}{_tag_chips(t)} {_anchor(t)}"


def _now_iso(settings: Settings, now: dt.datetime | None) -> str:
    return (now or dt.datetime.now(settings.tz)).isoformat(timespec="seconds")


def _default_post() -> frontmatter.Post:
    return frontmatter.Post(content=_HEADER)


def _load_post(path: Path) -> frontmatter.Post:
    return frontmatter.load(path) if path.exists() else _default_post()


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def load_last_seq(settings: Settings | None = None) -> int | None:
    """The current watermark from the inbox frontmatter, or None if unset."""
    settings = settings or get_settings()
    path = settings.inbox_file
    if not path.exists():
        return None
    v = frontmatter.load(path).metadata.get("last_seq")
    return int(v) if v is not None else None


def init_inbox(
    last_seq: int,
    *,
    settings: Settings | None = None,
    now: dt.datetime | None = None,
) -> Path:
    """Create the inbox note with an empty task list and the given watermark.

    Raises FileExistsError if the note already exists (use rewind/backfill via
    the CLI instead of clobbering a live inbox).
    """
    settings = settings or get_settings()
    path = settings.inbox_file
    if path.exists():
        raise FileExistsError(path)
    post = _default_post()
    post.metadata["last_seq"] = last_seq
    post.metadata["last_synced_at"] = _now_iso(settings, now)
    _atomic_write(path, frontmatter.dumps(post) + "\n")
    return path


def append_thoughts(
    thoughts: list[Thought],
    *,
    settings: Settings | None = None,
    now: dt.datetime | None = None,
) -> int:
    """Append task lines for `thoughts` and advance `last_seq`, atomically.

    Defensively drops any thought whose seq is already at/under the note's
    watermark, so a double-run can't duplicate lines. Returns the number of
    lines actually appended.
    """
    settings = settings or get_settings()
    path = settings.inbox_file
    post = _load_post(path)

    existing = post.metadata.get("last_seq")
    watermark = int(existing) if existing is not None else None
    new = sorted(
        (t for t in thoughts if watermark is None or t.seq > watermark),
        key=lambda t: t.seq,
    )
    if not new:
        return 0

    lines = "\n".join(render_line(t, settings.tz) for t in new)
    body = (post.content or "").rstrip()
    post.content = f"{body}\n{lines}\n"
    post.metadata["last_seq"] = max(t.seq for t in new)
    post.metadata["last_synced_at"] = _now_iso(settings, now)

    _atomic_write(path, frontmatter.dumps(post) + "\n")
    return len(new)


def count_task_lines(settings: Settings | None = None) -> int:
    """How many `- [ ]`/`- [x]` task lines the inbox currently holds."""
    settings = settings or get_settings()
    path = settings.inbox_file
    if not path.exists():
        return 0
    body = frontmatter.load(path).content or ""
    return sum(1 for ln in body.splitlines() if ln.lstrip().startswith(("- [ ]", "- [x]")))


__all__ = [
    "render_line",
    "load_last_seq",
    "init_inbox",
    "append_thoughts",
    "count_task_lines",
]
