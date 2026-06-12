"""Goldens: the renderer must reproduce the real 2026-06-10 check-in sections.

Fixtures are STATIC files committed to the repo (no live DB needed in CI):

* checkin_2026-06-10.md          — SYNTHETIC note in the exact marker-era
  shape (frontmatter + vault-review/memex-review marker sections + legacy
  agent-review section last).
* memex_captures_2026-06-10.json — synthetic memex.captures-shaped rows.
* agent_report_2026-06-10.json   — synthetic agent_review.daily_reports row
  (legacy narrative_md: full rendered section incl. trailing marker).

Fixtures are synthetic because this repo is PUBLIC and vault/report content
is private. Byte-equivalence against the REAL 2026-06-10 note and live rows
was verified at build time (2026-06-11) with the same assertions; these
fixtures pin the machinery (extraction, normalization, compose), not the
private content.

Documented normalizations (the renderer's output deliberately differs from
the historical note in exactly these ways — DESIGN.md):

1. memex heading: the note says `## memex-review — D — inbox`; the renderer's
   canonical heading is `## memex — D — inbox` because the memex-review tool
   dissolves (design decision 1, bracket example in decision 2).
2. per-section closing markers (`<!-- memex-review:daily=… -->`,
   `<!-- agent-review:report_date=… -->`) are dropped: the renderer's single
   begin/end bracket replaces the per-section marker protocols. For the agent
   section this IS the legacy-normalize branch (design decision 3).
3. the bracket's own `generated_at` is run-time-dependent; goldens pin it by
   injecting a fixed timestamp (design: "the only moving part").

Everything else must match byte-for-byte.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from checkin_renderer.compose import compose_bracket
from checkin_renderer.queries import AgentReportRow, CaptureRow
from checkin_renderer.sections.agent import render_agent_section
from checkin_renderer.sections.memex import render_memex_section

FIXTURES = Path(__file__).parent / "fixtures"
DATE = dt.date(2026, 6, 10)
TZ = ZoneInfo("America/Los_Angeles")


@pytest.fixture(scope="module")
def note_text() -> str:
    return (FIXTURES / "checkin_2026-06-10.md").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def capture_rows() -> list[CaptureRow]:
    data = json.loads((FIXTURES / "memex_captures_2026-06-10.json").read_text(encoding="utf-8"))
    return [
        CaptureRow(
            id=d["id"],
            content=d["content"],
            summary=d["summary"],
            tags=tuple(d["tags"]),
            created_at=dt.datetime.fromisoformat(d["created_at"]),
        )
        for d in data
    ]


@pytest.fixture(scope="module")
def agent_row() -> AgentReportRow:
    d = json.loads((FIXTURES / "agent_report_2026-06-10.json").read_text(encoding="utf-8"))
    return AgentReportRow(
        report_date=dt.date.fromisoformat(d["report_date"]),
        generated_at=dt.datetime.fromisoformat(d["generated_at"]),
        narrative_md=d["narrative_md"],
        stats=d["stats"],
    )


def _note_span(note_text: str, start_pat: str, end_pat: str) -> str:
    """Extract [start_pat, end_pat) from the note, end pattern excluded."""
    m = re.search(rf"{start_pat}.*?(?={end_pat})", note_text, re.DOTALL)
    assert m, f"section not found in note: {start_pat}"
    return m.group(0)


def test_memex_section_matches_real_note(note_text, capture_rows):
    expected = _note_span(
        note_text,
        r"## memex-review — 2026-06-10 — inbox",
        r"<!-- memex-review:daily=2026-06-10",  # normalization 2: marker dropped
    )
    # normalization 1: renderer canonical heading (memex-review dissolves)
    expected = expected.replace(
        "## memex-review — 2026-06-10 — inbox", "## memex — 2026-06-10 — inbox", 1
    ).rstrip()

    assert render_memex_section(capture_rows, DATE, TZ) == expected


def test_agent_section_matches_real_note(note_text, agent_row):
    expected = _note_span(
        note_text,
        r"## agent-review — 2026-06-11 00:23",
        r"<!-- agent-review:report_date=2026-06-10",  # normalization 2 / legacy-normalize
    ).rstrip()

    # legacy branch: stored narrative IS the full rendered section; body
    # (including the legacy timestamp heading) is reused verbatim
    assert render_agent_section(agent_row, DATE) == expected


def test_bracket_composes_both_golden_sections(note_text, capture_rows, agent_row):
    generated_at = dt.datetime(2026, 6, 11, 7, 51, 1, tzinfo=dt.UTC)  # normalization 3
    bracket = compose_bracket(
        DATE,
        {
            "memex": render_memex_section(capture_rows, DATE, TZ),
            "agent": render_agent_section(agent_row, DATE),
        },
        generated_at=generated_at,
    )
    lines = bracket.splitlines()
    assert lines[0] == "<!-- checkin-renderer:begin daily=2026-06-10 -->"
    assert lines[1] == "## memex — 2026-06-10 — inbox"
    assert (
        lines[-1]
        == "<!-- checkin-renderer:end daily=2026-06-10 generated_at=2026-06-11T07:51:01Z -->"
    )
    # memex section precedes agent section (SECTION_ORDER), separated by a blank line
    assert "\n\n## agent-review — 2026-06-11 00:23\n" in bracket
    # no marker-era closing comments survive inside the bracket
    assert "memex-review:daily=" not in bracket
    assert "agent-review:report_date=" not in bracket


def test_stored_narrative_matches_note_section_byte_for_byte(note_text, agent_row):
    """Sanity check on the fixtures themselves: the live DB row really is the
    full rendered section the marker-era writer put in the note (the premise
    of the legacy-normalize branch)."""
    note_section = _note_span(
        note_text,
        r"## agent-review — 2026-06-11 00:23",
        r"\n## |\Z",  # through the end of the note (it is the last section)
    )
    assert agent_row.narrative_md.strip() == note_section.strip()
