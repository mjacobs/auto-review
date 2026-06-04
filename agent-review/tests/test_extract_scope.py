"""Tests for agent_review.extract scope filtering."""

from __future__ import annotations

import datetime as dt

from agent_review.extract import SessionBundle, ToolSummary, _is_in_scope


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
