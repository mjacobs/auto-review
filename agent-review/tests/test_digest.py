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
        cwd="/home/user/projects/auto-review",
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


def test_artifact_key_aliases_are_coerced():
    """Local/cheaper models emit {path,type} artifacts instead of {kind,ref,note};
    the digest must coerce rather than reject the whole digest."""
    d = Digest.model_validate(
        {
            "summary": "did the thing",
            "project": "auto-review",
            "outcome": "exploration",
            "confidence": "high",
            "artifacts": [
                {"path": "memory/notes.md", "type": "file"},
                {"kind": "commit", "ref": "abc123", "note": "fix"},  # already conformant
            ],
        }
    )
    assert len(d.artifacts) == 2
    assert d.artifacts[0].kind == "file"
    assert d.artifacts[0].ref == "memory/notes.md"
    assert d.artifacts[0].note == ""
    # conformant entry survives unchanged
    assert d.artifacts[1].kind == "commit"
    assert d.artifacts[1].ref == "abc123"


def test_call_llm_reraises_underlying_error(monkeypatch: pytest.MonkeyPatch):
    """After retries are exhausted, the ORIGINAL exception (the real 404/
    RuntimeError) must propagate — not tenacity's opaque RetryError, which
    masked the 2026-06 digest outage for ~3 days. reraise=True makes this so."""
    from agent_review.config import Settings

    s = Settings(_env_file=None, PG_DSN="postgresql://u@h:5432/db")  # type: ignore[call-arg]
    monkeypatch.setattr(digest_mod, "get_settings", lambda: s)
    monkeypatch.setattr(digest_mod, "_load_system_prompt", lambda: "SYS")
    monkeypatch.setattr(digest_mod, "_render_user_payload", lambda b: "USER")

    calls: list[int] = []

    def boom(**kwargs):
        calls.append(1)
        raise RuntimeError("real 404: model not found")

    monkeypatch.setattr(digest_mod.llm, "complete", boom)
    # Don't actually sleep between the 4 attempts.
    monkeypatch.setattr(digest_mod._call_llm.retry, "wait", lambda *_a, **_k: 0)

    with pytest.raises(RuntimeError, match="real 404: model not found"):
        digest_mod._call_llm(_bundle())
    # all 4 attempts ran, then the raw RuntimeError surfaced (no RetryError)
    assert len(calls) == 4


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
