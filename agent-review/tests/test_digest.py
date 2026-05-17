"""Tests for agent_review.digest cache and prompt rendering."""

from __future__ import annotations

import datetime as dt

import pytest

from agent_review import digest as digest_mod
from agent_review.digest import Digest, get_or_create_digest_result
from agent_review.extract import SessionBundle, ToolSummary


def _digest(summary: str = "Did the thing.") -> Digest:
    return Digest(
        summary=summary,
        project="auto-review",
        tags=[],
        key_changes=[],
        artifacts=[],
        blockers=[],
        outcome="progressed",
        confidence="high",
    )


def _bundle(session_id: str = "parent") -> SessionBundle:
    return SessionBundle(
        session_id=session_id,
        agent="codex",
        machine="workstation",
        project="auto-review",
        project_source="cwd",
        cwd="/home/mj/dev/projects/auto-review",
        git_branch="main",
        started_at=dt.datetime(2026, 5, 16, 12, 0, tzinfo=dt.UTC),
        ended_at=dt.datetime(2026, 5, 16, 12, 30, tzinfo=dt.UTC),
        duration_minutes=30,
        message_count=5,
        user_message_count=2,
        peak_context_tokens=1000,
        total_output_tokens=200,
        outcome="progressed",
        outcome_confidence="high",
        health_grade="A",
        termination_status="completed",
        is_truncated=False,
        data_version=1,
        first_message="please fix the thing",
        transcript_text="[USER] please fix the thing\n\n[ASSISTANT] done",
        tool_summary=ToolSummary(
            total_calls=1,
            by_category={"Edit": 1},
            by_tool={"Edit": 1},
            top_bash_commands=[],
            files_touched=["src/example.py"],
        ),
        artifacts=[],
    )


def test_dry_run_digest_result_does_not_upsert(monkeypatch: pytest.MonkeyPatch):
    calls: list[str] = []
    usage = {"input_tokens": 10, "output_tokens": 5, "cache_read_input_tokens": 0}

    monkeypatch.setattr(digest_mod, "_load_cached_with_usage", lambda *_: None)
    monkeypatch.setattr(digest_mod, "_call_llm", lambda _: (_digest(), usage))
    monkeypatch.setattr(digest_mod, "_upsert", lambda *_: calls.append("upsert"))

    digest, returned_usage, fresh = get_or_create_digest_result(_bundle(), persist=False)

    assert digest.summary == "Did the thing."
    assert returned_usage == usage
    assert fresh is True
    assert calls == []


def test_cached_digest_result_avoids_llm(monkeypatch: pytest.MonkeyPatch):
    cached_usage = {"input_tokens": 20, "output_tokens": 7, "cache_read_input_tokens": 3}

    monkeypatch.setattr(
        digest_mod,
        "_load_cached_with_usage",
        lambda *_: (_digest("Cached."), cached_usage),
    )
    monkeypatch.setattr(
        digest_mod,
        "_call_llm",
        lambda _: pytest.fail("cache hit should not call LLM"),
    )

    digest, returned_usage, fresh = get_or_create_digest_result(_bundle(), persist=False)

    assert digest.summary == "Cached."
    assert returned_usage == cached_usage
    assert fresh is False


def test_render_user_payload_includes_folded_subagent_transcript():
    parent = _bundle("parent")
    child = _bundle("child")
    child.agent = "claude"
    child.first_message = "investigate the failing test"
    child.transcript_text = "[ASSISTANT] subagent found the root cause in digest.py"
    parent.subagents = [child]

    payload = digest_mod._render_user_payload(parent)

    assert "# subagents folded in (1)" in payload
    assert "# subagent transcripts (compressed)" in payload
    assert "subagent found the root cause in digest.py" in payload
