"""Tests for agent_review.extract scope filtering."""

from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

import pytest

import agent_review.extract as extract_mod
from agent_review.extract import (
    SessionBundle,
    ToolSummary,
    _fetch_session_rows,
    _infer_project,
    _is_in_scope,
)


def _bundle(
    *,
    outcome: str = "unknown",
    total_calls: int = 1,
    files_touched: list[str] | None = None,
) -> SessionBundle:
    return SessionBundle(
        session_id="session",
        agent="codex",
        machine="workstation",
        project="auto-review",
        project_source="cwd",
        cwd="/home/user/projects/auto-review",
        git_branch="main",
        started_at=dt.datetime(2026, 5, 16, 12, 0, tzinfo=dt.UTC),
        ended_at=dt.datetime(2026, 5, 16, 12, 30, tzinfo=dt.UTC),
        duration_minutes=30,
        message_count=5,
        user_message_count=2,
        peak_context_tokens=1000,
        total_output_tokens=200,
        outcome=outcome,
        outcome_confidence="low",
        health_grade=None,
        termination_status=None,
        is_truncated=False,
        data_version=1,
        first_message="please inspect this",
        transcript_text="[USER] please inspect this",
        tool_summary=ToolSummary(
            total_calls=total_calls,
            by_category={"Read": total_calls} if total_calls else {},
            by_tool={"Read": total_calls} if total_calls else {},
            top_bash_commands=[],
            files_touched=files_touched or [],
        ),
        artifacts=[],
    )


def test_unknown_outcome_read_only_session_is_out_of_scope():
    assert _is_in_scope(_bundle(files_touched=[])) is False


def test_unknown_outcome_with_file_write_activity_is_in_scope():
    assert _is_in_scope(_bundle(files_touched=["agent_review/digest.py"])) is True


def test_unknown_outcome_with_substantial_tool_activity_is_in_scope():
    assert _is_in_scope(_bundle(total_calls=10, files_touched=[])) is True


def test_known_outcome_read_only_session_can_still_be_in_scope():
    assert _is_in_scope(_bundle(outcome="progressed", files_touched=[])) is True


@pytest.mark.parametrize(
    ("cwd", "expected"),
    [
        ("/home/mj/dev/projects/agentsview", "agentsview"),
        ("/home/mj/dev/projects/agentsview/sub/dir", "agentsview"),
        ("/home/mj/dev/someproj", "someproj"),
    ],
)
def test_infer_project_prefers_specific_cwd_hint(cwd: str, expected: str):
    project, source = _infer_project(
        {"cwd": cwd, "git_branch": "main", "project": "workspace"}
    )

    assert project == expected
    assert source == "cwd"


@pytest.mark.parametrize("cwd", ["/home/mj/dev", "/home/mj/dev/projects"])
def test_infer_project_never_returns_hint_parent_words(cwd: str):
    project, _source = _infer_project(
        {"cwd": cwd, "git_branch": "main", "project": "workspace"}
    )

    assert project not in extract_mod._PROJECT_HINT_PARENTS


def test_infer_project_falls_back_to_git_branch():
    project, source = _infer_project(
        {"cwd": "", "git_branch": "feature/scope-fix", "project": "workspace"}
    )

    assert project == "feature/scope-fix"
    assert source == "git_branch"


def test_infer_project_falls_back_to_session_project():
    project, source = _infer_project(
        {"cwd": "", "git_branch": "main", "project": "auto-review"}
    )

    assert project == "auto-review"
    assert source == "session.project"


def test_fetch_session_rows_matches_start_or_end_day_not_broad_overlap(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        extract_mod,
        "get_settings",
        lambda: SimpleNamespace(pg_schema="agentsview"),
    )
    start = dt.datetime(2026, 5, 16, tzinfo=dt.UTC)
    end = start + dt.timedelta(days=1)
    cursor = _Cursor()
    rows = _fetch_session_rows(_Conn(cursor), start, end)

    assert rows == []
    assert "COALESCE(ended_at, started_at) >= %s" not in cursor.sql
    assert "(started_at >= %s AND started_at < %s)" in cursor.sql
    assert "(ended_at >= %s AND ended_at < %s)" in cursor.sql
    assert cursor.params == (start, end, start, end)


class _Cursor:
    sql = ""
    params = ()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, params):
        self.sql = sql
        self.params = params

    def fetchall(self):
        return []


class _Conn:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor
