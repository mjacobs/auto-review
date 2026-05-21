"""Git delta events for the vault repo.

Translates _git_delta_events from vault-agent into a parameterised form that
takes explicit (start_datetime, end_datetime) instead of a relative `since`
string, so callers can specify a day or an ISO week deterministically.
"""

from __future__ import annotations

import datetime as dt
import re
import subprocess
from pathlib import Path

# Paths that are structural / machine-generated and are not authoring signal.
# journal/checkins and journal/weekly are excluded because the auto-review
# siblings (vault-review/memex-review/agent-review/doctor) write back into
# them — including them recursively reports the siblings' own outputs as
# vault activity.
_DENYLIST_RE = re.compile(
    r"^(\.obsidian|\.git|archive|templates|x-attach|"
    r"journal/checkins|journal/weekly|"
    r"gemini-scribe/Agent-Sessions|gemini-scribe/Scheduled-Tasks)/"
)

# Type alias: (status, path1, path2_or_None)
Event = tuple[str, str, str | None]


def collect_events(
    vault_path: Path,
    start: dt.datetime,
    end: dt.datetime,
) -> list[Event]:
    """Return de-duplicated [(status, path1, path2_or_None)] for the window.

    Uses --diff-filter=AMDR -M so renames collapse into one event instead of
    showing up as add+delete pairs. Non-.md paths are dropped; paths matching
    _DENYLIST_RE are dropped. git log uses --since/--until with ISO-8601
    timestamps for deterministic, day-precise windows.

    Args:
        vault_path: Absolute path to the vault git repo.
        start: Inclusive window start (UTC or TZ-aware).
        end: Exclusive window end (UTC or TZ-aware).

    Returns:
        Ordered, de-duplicated list of (status, path1, path2_or_None).

    Raises:
        RuntimeError: If git log exits non-zero.
    """
    since_iso = start.isoformat()
    until_iso = end.isoformat()

    result = subprocess.run(
        [
            "git",
            "-C",
            str(vault_path),
            "log",
            f"--since={since_iso}",
            f"--until={until_iso}",
            "--no-merges",
            "--diff-filter=AMDR",
            "-M",
            "--name-status",
            "--pretty=format:",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"git log failed: {(result.stderr or result.stdout).strip()}"
        )

    seen: set[Event] = set()
    events: list[Event] = []
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        status = parts[0]
        path1 = parts[1] if len(parts) > 1 else ""
        path2: str | None = parts[2] if len(parts) > 2 else None
        effective = path2 or path1
        if _DENYLIST_RE.match(effective):
            continue
        if not effective.endswith(".md"):
            continue
        key: Event = (status, path1, path2)
        if key in seen:
            continue
        seen.add(key)
        events.append(key)
    return events
