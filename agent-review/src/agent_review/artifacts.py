"""
artifacts.py — Deterministic extractor for concrete artifacts from tool_calls.

Scans a session's tool_call rows and extracts:
  - git commits    (kind="commit")
  - git pushes     (kind="branch_push")
  - gh pr create   (kind="pr")
  - git tag        (kind="tag")
  - gh issue create (kind="issue")
  - Write/apply_patch (kind="file_write")
  - Edit           (kind="file_edit")

No LLM calls; all extraction is regex-based and deterministic.
"""

from __future__ import annotations

import json
import re
from typing import Literal, TypedDict

# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------

ArtifactKind = Literal["commit", "branch_push", "pr", "file_write", "file_edit", "issue", "tag"]


class Artifact(TypedDict):
    kind: ArtifactKind
    ref: str   # commit SHA, PR URL, file path, branch name, …
    note: str  # short human-readable label
    tool_call_id: int  # source tool_call.id


# ---------------------------------------------------------------------------
# Helpers: tool classification
# ---------------------------------------------------------------------------

_BASH_NAMES = {
    "bash", "Bash", "exec_command", "terminal",
    "run_shell_command", "shell",
}

_WRITE_NAMES = {
    "Write", "write",
    "apply_patch", "patch",
}

_EDIT_NAMES = {
    "Edit", "edit",
}


def _is_bash(tc: dict) -> bool:
    return tc.get("tool_name") in _BASH_NAMES or tc.get("category") == "Bash"


def _is_write(tc: dict) -> bool:
    return tc.get("tool_name") in _WRITE_NAMES or tc.get("category") == "Write"


def _is_edit(tc: dict) -> bool:
    return tc.get("tool_name") in _EDIT_NAMES or tc.get("category") == "Edit"


# ---------------------------------------------------------------------------
# Helpers: input_json parsing
# ---------------------------------------------------------------------------

def _parse_input(tc: dict) -> dict:
    """Return parsed input_json dict (may be empty); never raises."""
    raw = tc.get("input_json") or ""
    if not raw:
        return {}
    try:
        result = json.loads(raw)
        return result if isinstance(result, dict) else {}
    except (json.JSONDecodeError, ValueError):
        return {}


def _get_command(tc: dict) -> str:
    """Extract the shell command string from a bash-family tool call."""
    inp = _parse_input(tc)
    return inp.get("command") or inp.get("cmd") or ""


def _get_file_path(tc: dict) -> str:
    """Extract the file path from an Edit/Write tool call."""
    inp = _parse_input(tc)
    return inp.get("file_path") or inp.get("path") or ""


# ---------------------------------------------------------------------------
# Commit extraction
# ---------------------------------------------------------------------------

# -m "message" or -m 'message'
_M_INLINE = re.compile(r"""-m\s+["']([^"']+)["']""")

# heredoc: -m "$(cat <<'EOF'\n...\nEOF\n)"  or  -m "$(cat <<EOF\n...\nEOF)"
_M_HEREDOC = re.compile(
    r"""-m\s+["']\$\(cat\s*<<'?(\w+)'?\s*\n(.*?)\n\1\s*\)["']""",
    re.DOTALL,
)

# SHA from result: [branch abcdef1] or (root-commit 1234abc)
_RESULT_SHA = re.compile(r"\b([0-9a-f]{7,40})\b")
_RESULT_BRANCH_LINE = re.compile(r"\[([^\]]+?)\s+([0-9a-f]{7,40})\]")

_COAUTHORED = re.compile(r"^Co-Authored-By:", re.IGNORECASE)
_GIT_COMMIT_CMD = re.compile(r"\bgit\s+commit\b")


def _extract_commit_subject(command: str) -> str | None:
    """Return the commit message subject from a git commit command string."""
    # Try heredoc first (more specific)
    hm = _M_HEREDOC.search(command)
    if hm:
        body = hm.group(2)
        for line in body.splitlines():
            line = line.strip()
            if line and not _COAUTHORED.match(line):
                return line
        return None

    # Inline -m
    im = _M_INLINE.search(command)
    if im:
        return im.group(1).strip()

    return None


def _extract_commit_sha(result: str | None) -> str:
    """Try to pull a commit SHA out of the tool result text."""
    if not result:
        return "(unknown)"
    m = _RESULT_BRANCH_LINE.search(result)
    if m:
        return m.group(2)
    return "(unknown)"


def _extract_commits(tc: dict) -> list[Artifact]:
    cmd = _get_command(tc)
    if not _GIT_COMMIT_CMD.search(cmd):
        return []
    # Skip --amend-only meta calls that don't produce new commits, but still
    # extract; it's up to the caller to use first-occurrence dedup.
    subject = _extract_commit_subject(cmd)
    if subject is None:
        subject = "(no message)"
    sha = _extract_commit_sha(tc.get("result_content"))
    return [Artifact(kind="commit", ref=sha, note=subject, tool_call_id=tc["id"])]


# ---------------------------------------------------------------------------
# Push extraction
# ---------------------------------------------------------------------------

_GIT_PUSH_CMD = re.compile(r"\bgit\s+push\b")
# git push [-u] origin BRANCH  or git push origin HEAD:BRANCH
_PUSH_BRANCH = re.compile(
    r"\bgit\s+push\b(?:\s+--?\S+)*\s+\S+\s+([\w./-]+)"
)


def _extract_pushes(tc: dict) -> list[Artifact]:
    cmd = _get_command(tc)
    if not _GIT_PUSH_CMD.search(cmd):
        return []
    # Skip help invocations
    if re.search(r"(?:--help|-h\b)", cmd):
        return []
    m = _PUSH_BRANCH.search(cmd)
    branch = m.group(1) if m else "(unknown)"
    # Strip HEAD: prefix if present
    if branch.startswith("HEAD:"):
        branch = branch[5:]
    return [Artifact(kind="branch_push", ref=branch, note=f"push {branch}", tool_call_id=tc["id"])]


# ---------------------------------------------------------------------------
# PR extraction
# ---------------------------------------------------------------------------

_GH_PR_CREATE = re.compile(r"\bgh\s+pr\s+create\b")
_PR_TITLE = re.compile(r"""--title\s+["']([^"']+)["']""")
_PR_URL = re.compile(r"https://github\.com/[^\s]+/pull/\d+")


def _extract_prs(tc: dict) -> list[Artifact]:
    cmd = _get_command(tc)
    if not _GH_PR_CREATE.search(cmd):
        return []
    title_m = _PR_TITLE.search(cmd)
    title = title_m.group(1) if title_m else "(no title)"
    result = tc.get("result_content") or ""
    url_m = _PR_URL.search(result)
    url = url_m.group(0) if url_m else "(pending)"
    return [Artifact(kind="pr", ref=url, note=title, tool_call_id=tc["id"])]


# ---------------------------------------------------------------------------
# Tag extraction
# ---------------------------------------------------------------------------

_GIT_TAG_CMD = re.compile(r"\bgit\s+tag\b")

# Pure-list invocations that should NOT produce an artifact
_GIT_TAG_LIST = re.compile(r"\bgit\s+tag\b\s*(?:-l|--list|--sort[=\s]\S+)?\s*$")


def _extract_tags(tc: dict) -> list[Artifact]:
    cmd = _get_command(tc)
    if not _GIT_TAG_CMD.search(cmd):
        return []
    # Skip "git tag" / "git tag -l" / "git tag --list" (no tag name)
    if _GIT_TAG_LIST.search(cmd.strip()):
        return []
    # Extract the tag name: find the part after "git tag" and pick the first
    # token that does NOT start with '-' (i.e. not a flag).
    # Also handle quoted values from -m '...' by stopping at the first quoted block.
    after = _GIT_TAG_CMD.split(cmd, maxsplit=1)[-1]
    name: str | None = None
    for token in after.split():
        if not token.startswith("-") and not token.startswith("'") and not token.startswith('"'):
            name = token
            break
    if not name:
        return []
    return [Artifact(kind="tag", ref=name, note=f"tag {name}", tool_call_id=tc["id"])]


# ---------------------------------------------------------------------------
# Issue extraction
# ---------------------------------------------------------------------------

_GH_ISSUE_CREATE = re.compile(r"\bgh\s+issue\s+create\b")
_ISSUE_TITLE = re.compile(r"""--title\s+["']([^"']+)["']""")
_ISSUE_URL = re.compile(r"https://github\.com/[^\s]+/issues/\d+")


def _extract_issues(tc: dict) -> list[Artifact]:
    cmd = _get_command(tc)
    if not _GH_ISSUE_CREATE.search(cmd):
        return []
    title_m = _ISSUE_TITLE.search(cmd)
    title = title_m.group(1) if title_m else "(no title)"
    result = tc.get("result_content") or ""
    url_m = _ISSUE_URL.search(result)
    url = url_m.group(0) if url_m else "(pending)"
    return [Artifact(kind="issue", ref=url, note=title, tool_call_id=tc["id"])]


# ---------------------------------------------------------------------------
# File write extraction  (Write / apply_patch / patch)
# ---------------------------------------------------------------------------

# For apply_patch: look for "+++ b/PATH" or "path: /some/path"
# These patterns are applied to the *decoded* string values inside input_json,
# not the JSON-encoded form (which escapes newlines as \n).
_PATCH_PATH = re.compile(r"^\+{3}\s+b/(.+)$", re.MULTILINE)
_PATCH_PATH_KEY = re.compile(r"^path\s*:\s*(.+)$", re.MULTILINE)


def _extract_file_writes(tc: dict) -> list[Artifact]:
    name = tc.get("tool_name", "")
    if not _is_write(tc):
        return []

    if name in ("apply_patch", "patch"):
        inp = _parse_input(tc)
        paths: list[str] = []
        # Search each string value in the parsed dict for unified-diff path lines
        for v in inp.values():
            if not isinstance(v, str):
                continue
            for m in _PATCH_PATH.finditer(v):
                paths.append(m.group(1).strip())
            if not paths:
                for m in _PATCH_PATH_KEY.finditer(v):
                    paths.append(m.group(1).strip())
        if not paths:
            # Fall back to file_path / path keys
            p = _get_file_path(tc)
            if p:
                paths = [p]
        return [
            Artifact(kind="file_write", ref=p, note=f"write {p}", tool_call_id=tc["id"])
            for p in paths
        ]

    path = _get_file_path(tc)
    if not path:
        return []
    return [Artifact(kind="file_write", ref=path, note=f"write {path}", tool_call_id=tc["id"])]


# ---------------------------------------------------------------------------
# File edit extraction  (Edit)
# ---------------------------------------------------------------------------

def _extract_file_edits(tc: dict) -> list[Artifact]:
    if not _is_edit(tc):
        return []
    path = _get_file_path(tc)
    if not path:
        return []
    return [Artifact(kind="file_edit", ref=path, note=f"edit {path}", tool_call_id=tc["id"])]


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def extract_artifacts(tool_calls: list[dict]) -> list[Artifact]:
    """Return a deduplicated list of Artifacts extracted from *tool_calls*.

    Dedup rule: same (kind, ref) keeps only the *first* occurrence, EXCEPT
    for file edits where consecutive identical entries are dropped but
    non-consecutive repeats are kept.
    """
    raw: list[Artifact] = []

    for tc in tool_calls:
        if not isinstance(tc, dict):
            continue
        if _is_bash(tc):
            raw.extend(_extract_commits(tc))
            raw.extend(_extract_pushes(tc))
            raw.extend(_extract_prs(tc))
            raw.extend(_extract_tags(tc))
            raw.extend(_extract_issues(tc))
        if _is_write(tc):
            raw.extend(_extract_file_writes(tc))
        if _is_edit(tc):
            raw.extend(_extract_file_edits(tc))

    # Dedup
    # For non-edit kinds: keep first occurrence of (kind, ref).
    # For file_edit: drop consecutive identical (kind, ref) pairs only.
    seen: set[tuple[str, str]] = set()
    result: list[Artifact] = []
    prev_key: tuple[str, str] | None = None

    for art in raw:
        key = (art["kind"], art["ref"])
        if art["kind"] == "file_edit":
            # Drop consecutive duplicates only
            if key == prev_key:
                continue
            result.append(art)
            prev_key = key
        else:
            if key in seen:
                continue
            seen.add(key)
            result.append(art)
            prev_key = key

    return result
