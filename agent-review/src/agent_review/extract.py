"""Stage 1: pull in-scope sessions for a date and build session bundles.

A session bundle is the input to stage 2 (per-session digest). It contains:
- header metadata (agent, project, machine, timing, outcome, health, tokens)
- a compressed transcript (redacted, truncated)
- a tool-call summary (counts, top commands, files touched)
- artifacts (commits, PRs, files written/edited)
- folded subagent bundles (Claude only — other agents don't use subagents)
"""

from __future__ import annotations

import datetime as dt
import json
import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import PurePosixPath
from typing import Any

from .artifacts import Artifact, extract_artifacts
from .config import get_settings
from .db import connect
from .redaction import redact

# ─── tunables ──────────────────────────────────────────────────────────────────

MAX_MSG_CHARS = 8 * 1024            # truncate any single message above this
MIN_MESSAGES_FOR_SCOPE = 3          # below this, only count sessions with tool calls
MAX_TOP_COMMANDS = 10
MAX_FILES_TOUCHED = 30
TRIVIAL_SLASH_COMMANDS = re.compile(
    r"^/(exit|model|help|clear|cost|login|logout|init|compact|quit|status)\b\s*$",
    re.IGNORECASE,
)
# Heuristic: upstream is_automated flag is unreliable (false everywhere as of
# 2026-05). Treat sessions whose id begins with these prefixes as automated.
AUTOMATED_ID_PREFIXES = ("hermes:cron_",)

# ─── data shapes ───────────────────────────────────────────────────────────────


@dataclass
class ToolSummary:
    total_calls: int
    by_category: dict[str, int]
    by_tool: dict[str, int]
    top_bash_commands: list[str]
    files_touched: list[str]


@dataclass
class SessionBundle:
    session_id: str
    agent: str
    machine: str
    project: str
    project_source: str
    cwd: str
    git_branch: str
    started_at: dt.datetime
    ended_at: dt.datetime | None
    duration_minutes: int | None
    message_count: int
    user_message_count: int
    peak_context_tokens: int
    total_output_tokens: int
    outcome: str
    outcome_confidence: str
    health_grade: str | None
    termination_status: str | None
    is_truncated: bool
    data_version: int
    first_message: str
    transcript_text: str
    tool_summary: ToolSummary
    artifacts: list[Artifact]
    subagents: list[SessionBundle] = field(default_factory=list)
    is_subagent: bool = False

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["started_at"] = self.started_at.isoformat()
        d["ended_at"] = self.ended_at.isoformat() if self.ended_at else None
        return d


# ─── public entry points ───────────────────────────────────────────────────────


def day_window(date: dt.date) -> tuple[dt.datetime, dt.datetime]:
    """Return [start, end) UTC instants for the given local-tz date."""
    tz = get_settings().tz
    start = dt.datetime.combine(date, dt.time.min, tzinfo=tz)
    return start, start + dt.timedelta(days=1)


def extract_day(date: dt.date) -> list[SessionBundle]:
    """Return all in-scope session bundles for the given local-tz date,
    with subagents folded into their parents."""
    start, end = day_window(date)
    with connect() as conn:
        rows = _fetch_session_rows(conn, start, end)
        if not rows:
            return []
        # Pull subagent rows that may have started outside the window (rare) but
        # whose parent is in the window — we'll find them per-parent below.
        parent_bundles: list[SessionBundle] = []
        for row in rows:
            if row["parent_session_id"]:
                # subagents are folded into parents below; skip if parent is in
                # this same window (it will pick them up). If parent is outside
                # the window, treat orphan subagent as its own session.
                continue
            bundle = _build_bundle(conn, row)
            bundle.subagents = _collect_subagents(conn, row["id"])
            parent_bundles.append(bundle)

        # Orphan subagents whose parent is outside the window
        orphan_rows = [r for r in rows if r["parent_session_id"]
                       and not _parent_in_set(r["parent_session_id"], rows)]
        for row in orphan_rows:
            bundle = _build_bundle(conn, row)
            bundle.is_subagent = True
            parent_bundles.append(bundle)

    in_scope = [b for b in parent_bundles if _is_in_scope(b)]
    return in_scope


def extract_session(session_id: str) -> SessionBundle | None:
    """Pull a single session by id (no scope filter, no subagent folding)."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM agentsview.sessions WHERE id = %s",
            (session_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        bundle = _build_bundle(conn, row)
        bundle.subagents = _collect_subagents(conn, session_id)
        return bundle


# ─── DB helpers ────────────────────────────────────────────────────────────────


def _fetch_session_rows(conn, start: dt.datetime, end: dt.datetime) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT *
              FROM agentsview.sessions
             WHERE started_at >= %s AND started_at < %s
               AND is_automated = false
               AND deleted_at IS NULL
             ORDER BY started_at
            """,
            (start, end),
        )
        return list(cur.fetchall())


def _parent_in_set(parent_id: str, rows: list[dict]) -> bool:
    return any(r["id"] == parent_id for r in rows)


def _collect_subagents(conn, parent_id: str) -> list[SessionBundle]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM agentsview.sessions WHERE parent_session_id = %s ORDER BY started_at",
            (parent_id,),
        )
        children = list(cur.fetchall())
    out: list[SessionBundle] = []
    for child in children:
        b = _build_bundle(conn, child)
        b.is_subagent = True
        out.append(b)
    return out


def _fetch_messages(conn, session_id: str) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT ordinal, role, content, content_length, "timestamp",
                   is_sidechain, is_compact_boundary, has_tool_use
              FROM agentsview.messages
             WHERE session_id = %s
             ORDER BY ordinal
            """,
            (session_id,),
        )
        return list(cur.fetchall())


def _fetch_tool_calls(conn, session_id: str) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, session_id, tool_name, category, call_index, tool_use_id,
                   input_json, result_content, subagent_session_id, message_ordinal
              FROM agentsview.tool_calls
             WHERE session_id = %s
             ORDER BY message_ordinal, call_index
            """,
            (session_id,),
        )
        return list(cur.fetchall())


# ─── bundle assembly ──────────────────────────────────────────────────────────


def _build_bundle(conn, row: dict) -> SessionBundle:
    msgs = _fetch_messages(conn, row["id"])
    tools = _fetch_tool_calls(conn, row["id"])

    project, source = _infer_project(row)
    transcript = _compress_transcript(msgs)
    tool_summary = _summarize_tools(tools)
    artifacts = extract_artifacts(tools)
    duration = _duration_minutes(row["started_at"], row.get("ended_at"))
    first_msg = (row.get("first_message") or "").strip()
    if len(first_msg) > 1000:
        first_msg = first_msg[:1000] + "…"
    first_msg = redact(first_msg)

    return SessionBundle(
        session_id=row["id"],
        agent=row["agent"],
        machine=row["machine"],
        project=project,
        project_source=source,
        cwd=row.get("cwd") or "",
        git_branch=row.get("git_branch") or "",
        started_at=row["started_at"],
        ended_at=row.get("ended_at"),
        duration_minutes=duration,
        message_count=row["message_count"],
        user_message_count=row["user_message_count"],
        peak_context_tokens=row.get("peak_context_tokens") or 0,
        total_output_tokens=row.get("total_output_tokens") or 0,
        outcome=row.get("outcome") or "unknown",
        outcome_confidence=row.get("outcome_confidence") or "low",
        health_grade=row.get("health_grade"),
        termination_status=row.get("termination_status"),
        is_truncated=bool(row.get("is_truncated")),
        data_version=row.get("data_version") or 0,
        first_message=first_msg,
        transcript_text=transcript,
        tool_summary=tool_summary,
        artifacts=artifacts,
    )


# ─── project inference ────────────────────────────────────────────────────────

_PROJECT_HINT_PARENTS = {"projects", "dev", "src", "code", "workspace"}


def _infer_project(row: dict) -> tuple[str, str]:
    """Infer a clean project name. Prefer cwd/git_branch over the noisy
    sessions.project field (which is often "workspace" or "mj")."""
    cwd = (row.get("cwd") or "").strip()
    branch = (row.get("git_branch") or "").strip()
    fallback = (row.get("project") or "unknown").strip() or "unknown"

    if cwd:
        parts = PurePosixPath(cwd).parts
        # ~/dev/projects/<name>/sub → <name>
        for i, p in enumerate(parts):
            if p in _PROJECT_HINT_PARENTS and i + 1 < len(parts):
                return parts[i + 1], "cwd"
        # last meaningful path segment, skipping $HOME-ish noise
        meaningful = [p for p in parts if p not in {"/", "home", "mj", "Users"}]
        if meaningful:
            return meaningful[-1], "cwd"

    if branch and branch not in {"HEAD", "main", "master"}:
        return branch, "git_branch"

    return fallback, "session.project"


# ─── transcript compression ───────────────────────────────────────────────────


def _compress_transcript(messages: list[dict]) -> str:
    """Format messages as a compact text transcript, dropping sidechain/compact
    boundaries, truncating large messages, and redacting secrets."""
    out: list[str] = []
    for m in messages:
        if m.get("is_sidechain"):
            continue
        if m.get("is_compact_boundary"):
            out.append("\n--- [compact boundary] ---\n")
            continue
        role = m["role"]
        content = (m.get("content") or "").strip()
        if not content:
            continue
        if len(content) > MAX_MSG_CHARS:
            head = content[: MAX_MSG_CHARS // 2]
            tail = content[-MAX_MSG_CHARS // 2 :]
            elided = len(content) - MAX_MSG_CHARS
            content = f"{head}\n…[{elided} bytes elided]…\n{tail}"
        ts = m.get("timestamp")
        ts_str = ts.strftime("%H:%M") if isinstance(ts, dt.datetime) else "?"
        out.append(f"[{role.upper()} {ts_str}] {content}")
    text = "\n\n".join(out)
    return redact(text)


# ─── tool summary ────────────────────────────────────────────────────────────


_BASH_TOOLS = {"Bash", "bash", "exec_command", "terminal", "run_shell_command", "shell"}
_FILE_TOOLS = {"Edit", "edit", "Write", "write", "apply_patch", "patch"}


def _summarize_tools(tool_calls: list[dict]) -> ToolSummary:
    by_cat: Counter[str] = Counter()
    by_tool: Counter[str] = Counter()
    bash_cmds: list[str] = []
    files: list[str] = []

    for tc in tool_calls:
        by_cat[tc.get("category") or "Other"] += 1
        by_tool[tc.get("tool_name") or "(unknown)"] += 1
        try:
            payload = json.loads(tc.get("input_json") or "{}")
        except (json.JSONDecodeError, TypeError):
            payload = {}

        if tc.get("tool_name") in _BASH_TOOLS:
            cmd = (payload.get("command") or payload.get("cmd") or "").strip()
            if cmd:
                first_line = cmd.splitlines()[0].strip()
                if len(first_line) > 200:
                    first_line = first_line[:197] + "…"
                bash_cmds.append(first_line)
        elif tc.get("tool_name") in _FILE_TOOLS:
            path = (payload.get("file_path") or payload.get("path") or "").strip()
            if path:
                files.append(path)

    top_bash = [cmd for cmd, _ in Counter(bash_cmds).most_common(MAX_TOP_COMMANDS)]
    # files_touched: dedupe, preserve order
    seen: set[str] = set()
    file_list: list[str] = []
    for f in files:
        if f not in seen:
            seen.add(f)
            file_list.append(f)
        if len(file_list) >= MAX_FILES_TOUCHED:
            break

    return ToolSummary(
        total_calls=sum(by_cat.values()),
        by_category=dict(by_cat),
        by_tool=dict(by_tool),
        top_bash_commands=top_bash,
        files_touched=file_list,
    )


# ─── scope filter ─────────────────────────────────────────────────────────────


def _is_in_scope(b: SessionBundle) -> bool:
    """Apply post-query scope filters."""
    # 0. Heuristic automation prefixes (upstream is_automated is unreliable)
    if any(b.session_id.startswith(p) for p in AUTOMATED_ID_PREFIXES):
        return False
    # 1. Trivial slash-command-only sessions
    if b.message_count <= 1 and TRIVIAL_SLASH_COMMANDS.match(b.first_message.strip()):
        return False
    # 2. Below message threshold AND no tool calls
    if b.message_count < MIN_MESSAGES_FOR_SCOPE and b.tool_summary.total_calls == 0:
        return False
    # 3. Unknown-outcome sessions must show concrete write/edit activity.
    return b.outcome != "unknown" or _has_file_write_activity(b)


def _has_file_write_activity(b: SessionBundle) -> bool:
    if b.tool_summary.files_touched:
        return True
    return any(a["kind"] in {"file_write", "file_edit"} for a in b.artifacts)


# ─── timing helper ────────────────────────────────────────────────────────────


def _duration_minutes(start: dt.datetime | None, end: dt.datetime | None) -> int | None:
    if not start or not end:
        return None
    return max(0, int((end - start).total_seconds() / 60))
