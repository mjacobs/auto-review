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
    for ln in lines[body_start:]:
        if _FENCE_RE.match(ln):
            # Toggle code-fence state and skip the delimiter; a fence opener
            # like ```` ```tasks ```` is not a meaningful summary paragraph.
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        hm = _HEADING_RE.match(ln)
        if hm:
            heading = _sanitize_summary(hm.group(1))
            continue
        if ln.strip():
            body = _sanitize_summary(ln)
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
