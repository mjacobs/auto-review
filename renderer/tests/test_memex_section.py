"""Unit tests for the memex inbox section (port of memex-review's renderer)."""

from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

from checkin_renderer.queries import CaptureRow
from checkin_renderer.sections.memex import render_memex_section

TZ = ZoneInfo("America/Los_Angeles")
DATE = dt.date(2026, 6, 10)


def _row(
    iso_utc: str,
    *,
    content: str = "some content",
    summary: str | None = None,
    tags: tuple[str, ...] = (),
    capture_id: str = "c1",
) -> CaptureRow:
    return CaptureRow(
        id=capture_id,
        content=content,
        summary=summary,
        tags=tags,
        created_at=dt.datetime.fromisoformat(iso_utc),
    )


def test_empty_window_renders_zero_captures_placeholder():
    out = render_memex_section([], DATE, TZ)
    assert out == (
        "## memex — 2026-06-10 — inbox\n"
        "\n"
        "_window: 2026-06-10 — 0 captures_\n"
        "\n"
        "_no captures in window_"
    )


def test_single_capture_with_summary_and_tags():
    rows = [
        _row(
            "2026-06-10T08:01:24.439+00:00",  # 01:01 PDT
            content="project idea:   agentview mcp",
            summary="agentview mcp is a project idea.",
            tags=("agentview", "mcp"),
        )
    ]
    out = render_memex_section(rows, DATE, TZ)
    assert out == (
        "## memex — 2026-06-10 — inbox\n"
        "\n"
        "_window: 2026-06-10 — 1 capture_\n"
        "\n"
        "- 01:01 — agentview mcp is a project idea. `[#agentview #mcp]`"
    )


def test_summary_fallback_takes_first_nonempty_content_line_collapsed():
    rows = [_row("2026-06-10T19:00:00+00:00", content="\n\n  first   line \nsecond line")]
    out = render_memex_section(rows, DATE, TZ)
    assert "- 12:00 — first line" in out
    assert "second line" not in out


def test_blank_content_renders_empty_placeholder_line():
    rows = [_row("2026-06-10T19:00:00+00:00", content="   \n  ")]
    assert "- 12:00 — (empty)" in render_memex_section(rows, DATE, TZ)


def test_captures_sorted_ascending_by_created_at():
    rows = [
        _row("2026-06-10T22:00:00+00:00", summary="later", capture_id="b"),
        _row("2026-06-10T08:00:00+00:00", summary="earlier", capture_id="a"),
    ]
    out = render_memex_section(rows, DATE, TZ)
    lines = [ln for ln in out.splitlines() if ln.startswith("- ")]
    assert lines == ["- 01:00 — earlier", "- 15:00 — later"]


def test_plural_capture_count():
    rows = [
        _row("2026-06-10T08:00:00+00:00", capture_id="a"),
        _row("2026-06-10T09:00:00+00:00", capture_id="b"),
    ]
    assert "_window: 2026-06-10 — 2 captures_" in render_memex_section(rows, DATE, TZ)
