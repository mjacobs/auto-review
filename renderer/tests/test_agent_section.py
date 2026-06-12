"""Unit tests for the agent-review section (legacy-normalize + canonical paths)."""

from __future__ import annotations

import datetime as dt

from checkin_renderer.queries import AgentReportRow
from checkin_renderer.sections.agent import is_legacy_row, render_agent_section

DATE = dt.date(2026, 6, 10)
GENERATED_AT = dt.datetime(2026, 6, 11, 7, 23, tzinfo=dt.UTC)


def _report(narrative_md: str, stats: dict | None = None) -> AgentReportRow:
    return AgentReportRow(
        report_date=DATE,
        generated_at=GENERATED_AT,
        narrative_md=narrative_md,
        stats=stats or {},
    )


LEGACY = (
    "## agent-review — 2026-06-11 00:23\n"
    "\n"
    "_window: 2026-06-10 00:00 → 00:23 America/Los_Angeles · 2 sessions_\n"
    "\n"
    "### narrative\n"
    "\n"
    "Built a thing.\n"
    "\n"
    "### stats\n"
    "\n"
    "| sessions |\n|---------:|\n| 2 |\n"
    "\n"
    "<!-- agent-review:report_date=2026-06-10 generated_at=2026-06-11T00:23:20-07:00 -->\n"
)


def test_missing_row_renders_placeholder():
    out = render_agent_section(None, DATE)
    assert out == (
        "## agent-review — 2026-06-10\n\n_no agent-review report row for 2026-06-10_"
    )


def test_legacy_row_detection():
    assert is_legacy_row(LEGACY)
    assert not is_legacy_row("Plain narrative prose.")


def test_legacy_normalize_strips_trailing_marker_and_reuses_body_verbatim():
    out = render_agent_section(_report(LEGACY), DATE)
    # body verbatim — including the legacy "## agent-review — <ts>" heading —
    # minus the trailing marker comment (it dies with the marker protocol)
    assert out.startswith("## agent-review — 2026-06-11 00:23\n")
    assert "agent-review:report_date=" not in out
    assert out.endswith("| 2 |")
    assert out == LEGACY.split("\n<!--")[0].rstrip()


def test_legacy_normalize_handles_missing_trailing_newline():
    legacy = LEGACY.rstrip("\n")
    out = render_agent_section(_report(legacy), DATE)
    assert "agent-review:report_date=" not in out
    assert out.endswith("| 2 |")


def test_canonical_render_from_clean_narrative_and_stats():
    stats = {
        "sessions": 3,
        "agents": {"claude": 2, "codex": 1},
        "projects": {"a": 2, "b": 1},
        "messages": 100,
        "session_output_tokens_sum": 5000,
        "peak_context_tokens_max": 9000,
        "artifact_count": 4,
        "blocker_count": 1,
        "est_total_cost_usd": 0.0471,
    }
    out = render_agent_section(_report("A clean narrative.", stats), DATE)
    assert out.startswith("## agent-review — 2026-06-10\n")
    assert "_3 sessions · 2 projects · ~$0.05 · claude×2, codex×1_" in out
    assert "A clean narrative." in out
    assert "### stats" in out
    assert "| 3 | claude×2, codex×1 | 100 | 5000 | 9000 | 4 | 1 | $0.0471 |" in out
