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
                    return v
        else:
            body_start = len(lines)
    heading = ""
    for ln in lines[body_start:]:
        hm = _HEADING_RE.match(ln)
        if hm:
            heading = hm.group(1).strip()
            continue
        if ln.strip():
            return f"{heading} — {ln.strip()}" if heading else ln.strip()
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
