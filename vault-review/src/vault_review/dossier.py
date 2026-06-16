"""Render a human-readable dossier from vault git-delta events.

Translates _summarize_file, _group_of, and _render_dossier from vault-agent
into standalone functions that take an explicit vault_path parameter rather
than relying on a module-level VAULT constant.
"""

from __future__ import annotations

import re
from pathlib import Path

from .gitdelta import Event

_FRONTMATTER_DESC_RE = re.compile(r"^description:\s*(.+?)\s*$")
_HEADING_RE = re.compile(r"^#+\s+(.*)$")
_FENCE_RE = re.compile(r"^\s*(```|~~~)")
_EMPHASIS_RE = re.compile(r"[*_`]+")

# Non-prose constructs a note can lead with that must be skipped when hunting
# for the first meaningful summary line. Without these, the raw markup leaks
# into the one-line bullet (e.g. a `<style>` opener or a `> [!WARNING]` callout
# marker rendered verbatim as the file's "summary").
_HTML_BLOCK_OPEN_RE = re.compile(r"^\s*<(?:style|script)\b", re.IGNORECASE)
_HTML_BLOCK_CLOSE_RE = re.compile(r"</(?:style|script)\s*>", re.IGNORECASE)
_HTML_COMMENT_OPEN_RE = re.compile(r"^\s*<!--")
_HTML_COMMENT_CLOSE_RE = re.compile(r"-->")
# A line that is nothing but an HTML tag (a bare `<div>`/`</div>` wrapper).
# Tightened so it does not swallow autolinks like `<https://example.com>`.
_HTML_TAG_ONLY_RE = re.compile(r"^\s*</?[a-zA-Z][\w-]*(?:\s[^>]*)?>\s*$")
# An auto-generated table-of-contents entry: a list item that is only an
# in-page anchor link. Links to other notes (no leading `#`) are not skipped.
_TOC_LINK_RE = re.compile(r"^\s*[-*+]\s*\[[^\]]*\]\(#[^)]*\)\s*$")
_BLOCKQUOTE_RE = re.compile(r"^\s*>+\s?")
_CALLOUT_RE = re.compile(r"^\[!\w+\][+-]?\s*(.*)$")

_SUMMARY_MAX = 120


def _sanitize_summary(text: str) -> str:
    """Flatten a body line into safe inline bullet text.

    The summary is dropped onto a single `- ... — <summary>` line, so any raw
    markdown it carries (emphasis runs, backticks, code-fence markers) leaks
    into the surrounding bullet and corrupts rendering. Strip those markers,
    collapse whitespace, and truncate so the line stays a one-liner.
    """
    text = _EMPHASIS_RE.sub("", text)
    text = " ".join(text.split())
    if len(text) > _SUMMARY_MAX:
        text = text[: _SUMMARY_MAX - 1].rstrip() + "…"
    return text


def summarize_file(vault_path: Path, rel: str) -> str:
    """Return a 1-line summary of a vault note.

    Tries (in order): frontmatter `description` field, first heading +
    first non-empty body paragraph, fallback to heading alone.
    """
    p = vault_path / rel
    if not p.is_file():
        return "(no longer present)"
    try:
        text = p.read_text(errors="replace")
    except OSError:
        return "(unreadable)"
    lines = text.splitlines()
    body_start = 0
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                body_start = i + 1
                break
            m = _FRONTMATTER_DESC_RE.match(lines[i])
            if m:
                v = m.group(1).strip().strip('"').strip("'")
                if v:
                    return _sanitize_summary(v)
        else:
            body_start = len(lines)
    heading = ""
    in_fence = False
    in_html_block = False
    in_comment = False
    for ln in lines[body_start:]:
        if _FENCE_RE.match(ln):
            # Toggle code-fence state and skip the delimiter; a fence opener
            # like ```` ```tasks ```` is not a meaningful summary paragraph.
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        # Skip embedded <style>/<script> blocks; some notes lead with CSS.
        if in_html_block:
            if _HTML_BLOCK_CLOSE_RE.search(ln):
                in_html_block = False
            continue
        if _HTML_BLOCK_OPEN_RE.match(ln):
            if not _HTML_BLOCK_CLOSE_RE.search(ln):
                in_html_block = True
            continue
        # Skip HTML comments, including multi-line (e.g. <!--toc:start--> blocks).
        if in_comment:
            if _HTML_COMMENT_CLOSE_RE.search(ln):
                in_comment = False
            continue
        if _HTML_COMMENT_OPEN_RE.match(ln):
            if not _HTML_COMMENT_CLOSE_RE.search(ln):
                in_comment = True
            continue
        if _TOC_LINK_RE.match(ln) or _HTML_TAG_ONLY_RE.match(ln):
            continue
        hm = _HEADING_RE.match(ln)
        if hm:
            heading = _sanitize_summary(hm.group(1))
            continue
        # Blockquotes / Obsidian callouts: unwrap the `>` markers. A bare
        # callout marker (`> [!WARNING]`) carries no prose, so descend to the
        # callout body; a marker with an inline title uses that title.
        if _BLOCKQUOTE_RE.match(ln):
            inner = ln
            while _BLOCKQUOTE_RE.match(inner):
                inner = _BLOCKQUOTE_RE.sub("", inner, count=1)
            cm = _CALLOUT_RE.match(inner.strip())
            if cm:
                inner = cm.group(1)
            inner = inner.strip()
            if not inner:
                continue
            body = _sanitize_summary(inner)
            if body:
                return f"{heading} — {body}" if heading else body
            continue
        if ln.strip():
            body = _sanitize_summary(ln)
            if body:
                return f"{heading} — {body}" if heading else body
    return heading or "(empty)"


def group_of(rel: str) -> str:
    """Return a grouping key for a vault-relative path.

    Paths under `projects/<name>/...` become `projects/<name>`.
    Paths under any other top-level directory become that directory name.
    Root-level files become `(root)`.
    """
    parts = rel.split("/")
    if parts[0] == "projects" and len(parts) >= 3:
        return "projects/" + parts[1]
    return parts[0] if len(parts) > 1 else "(root)"


def render_dossier(
    vault_path: Path,
    events: list[Event],
    window_label: str,
    heading: str,
) -> str:
    """Render a markdown dossier section from vault git-delta events.

    Returns the full markdown string for the dossier section (no trailing
    closing marker — the vault writer adds that).

    Args:
        vault_path: Absolute path to the vault repo (used for file summaries).
        events: List of (status, path1, path2_or_None) from collect_events().
        window_label: Human-readable window description, e.g. "2026-05-14".
        heading: Heading text, e.g. "vault-review — 2026-05-14".
    """
    by_group: dict[str, list[str]] = {}
    for status, p1, p2 in events:
        effective = p2 or p1
        g = group_of(effective)
        if status == "A":
            line = f"- `+` `{effective}` — {summarize_file(vault_path, effective)}"
        elif status == "M":
            line = f"- `~` `{effective}` — {summarize_file(vault_path, effective)}"
        elif status == "D":
            line = f"- `-` `{p1}`"
        elif status.startswith("R"):
            line = f"- `↻` `{p2}` (renamed from `{p1}`)"
        else:
            line = f"- `?` {status} `{effective}`"
        by_group.setdefault(g, []).append(line)

    out = [f"## {heading}", "", f"_window: {window_label}_", ""]
    if not by_group:
        out += ["_no authored changes in window_", ""]
        return "\n".join(out)
    for g in sorted(by_group):
        out.append(f"### {g}")
        out.extend(by_group[g])
        out.append("")
    return "\n".join(out)
