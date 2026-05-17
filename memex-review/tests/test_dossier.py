"""Tests for the inbox dossier renderer."""

from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

from memex_review.client import Thought
from memex_review.dossier import render_dossier

LA = ZoneInfo("America/Los_Angeles")


def _t(
    ts_iso: str,
    *,
    tags: tuple[str, ...] = (),
    summary: str | None = None,
    preview: str = "",
    id_: str | None = None,
) -> Thought:
    when = dt.datetime.fromisoformat(ts_iso)
    if when.tzinfo is None:
        when = when.replace(tzinfo=dt.timezone.utc)
    ms = int(when.timestamp() * 1000)
    return Thought(
        id=id_ or f"id-{ts_iso}",
        content_preview=preview,
        source=None,
        summary=summary,
        tags=tags,
        created_at_ms=ms,
        updated_at_ms=ms,
    )


def test_empty_renders_placeholder() -> None:
    out = render_dossier([], "2026-05-14", "memex-review — 2026-05-14 — inbox", LA)
    assert "## memex-review — 2026-05-14 — inbox" in out
    assert "_window: 2026-05-14 — 0 captures_" in out
    assert "_no captures in window_" in out
    assert "- " not in out  # no bullet lines


def test_single_capture_uses_singular_count() -> None:
    out = render_dossier([_t("2026-05-14T16:00:00", summary="hi")], "2026-05-14", "h", LA)
    assert "1 capture_" in out
    assert "captures" not in out  # not "1 captures"


def test_flat_chronological_oldest_first() -> None:
    thoughts = [
        _t("2026-05-14T20:00:00", summary="late"),
        _t("2026-05-14T08:00:00", summary="early"),
        _t("2026-05-14T14:00:00", summary="mid"),
    ]
    out = render_dossier(thoughts, "2026-05-14", "h", LA)
    bullets = [ln for ln in out.splitlines() if ln.startswith("- ")]
    assert len(bullets) == 3
    texts = [b.split(" — ", 1)[1] for b in bullets]
    assert texts[0].startswith("early")
    assert texts[1].startswith("mid")
    assert texts[2].startswith("late")


def test_no_section_headers_rendered() -> None:
    """The inbox is flat — never produce ### subsections."""
    thoughts = [
        _t("2026-05-14T16:00:00", tags=("alpha", "bravo"), summary="dual"),
        _t("2026-05-14T17:00:00", tags=("alpha",), summary="solo"),
    ]
    out = render_dossier(thoughts, "2026-05-14", "h", LA)
    assert "### " not in out


def test_no_bullet_duplication_for_multi_tag_captures() -> None:
    """Multi-tag captures appear exactly once (vs old tag-grouped behavior)."""
    thoughts = [_t("2026-05-14T16:00:00", tags=("a", "b", "c", "d"), summary="once")]
    out = render_dossier(thoughts, "2026-05-14", "h", LA)
    assert out.count("once") == 1


def test_tag_chips_inline() -> None:
    thoughts = [_t("2026-05-14T16:00:00", tags=("alpha", "bravo"), summary="s")]
    out = render_dossier(thoughts, "2026-05-14", "h", LA)
    assert "`[#alpha #bravo]`" in out


def test_no_chip_group_when_untagged() -> None:
    thoughts = [_t("2026-05-14T16:00:00", tags=(), summary="s")]
    out = render_dossier(thoughts, "2026-05-14", "h", LA)
    bullet = [ln for ln in out.splitlines() if ln.startswith("- ")][0]
    assert bullet == "- 09:00 — s"  # no trailing chip group
    assert "[" not in bullet


def test_line_text_prefers_summary_over_preview() -> None:
    thoughts = [_t("2026-05-14T16:00:00", summary="the summary", preview="the preview")]
    out = render_dossier(thoughts, "2026-05-14", "h", LA)
    assert "— the summary" in out
    assert "the preview" not in out


def test_line_text_falls_back_to_preview_and_collapses_whitespace() -> None:
    thoughts = [_t("2026-05-14T16:00:00", preview="line one\nline two\nline three")]
    out = render_dossier(thoughts, "2026-05-14", "h", LA)
    bullet = [ln for ln in out.splitlines() if ln.startswith("- ")][0]
    assert bullet.endswith("— line one")


def test_hhmm_rendered_in_local_tz() -> None:
    # 20:00 UTC = 13:00 America/Los_Angeles (PDT, UTC-7) in May.
    thoughts = [_t("2026-05-14T20:00:00", summary="s")]
    out = render_dossier(thoughts, "2026-05-14", "h", LA)
    assert "- 13:00 — s" in out


def test_empty_summary_and_preview_renders_empty_marker() -> None:
    thoughts = [_t("2026-05-14T16:00:00", tags=("x",))]
    out = render_dossier(thoughts, "2026-05-14", "h", LA)
    assert "— (empty)" in out
