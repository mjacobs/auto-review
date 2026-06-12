"""Unit tests for bracket composition (section order, markers, skips)."""

from __future__ import annotations

import datetime as dt

import pytest

from checkin_renderer.compose import (
    SECTION_ORDER,
    compose_bracket,
    compose_full,
    default_daily_post,
)

DATE = dt.date(2026, 6, 10)
NOW = dt.datetime(2026, 6, 11, 7, 51, 1, tzinfo=dt.UTC)


def test_bracket_wraps_sections_in_begin_end_pair():
    out = compose_bracket(
        DATE,
        {"memex": "## memex — x", "agent": "## agent-review — y"},
        generated_at=NOW,
    )
    assert out == (
        "<!-- checkin-renderer:begin daily=2026-06-10 -->\n"
        "## memex — x\n"
        "\n"
        "## agent-review — y\n"
        "<!-- checkin-renderer:end daily=2026-06-10 generated_at=2026-06-11T07:51:01Z -->"
    )


def test_section_order_is_the_literal_list_not_mapping_order():
    out = compose_bracket(
        DATE,
        {"agent": "AGENT", "projects": "PROJECTS", "memex": "MEMEX", "health": "HEALTH"},
        generated_at=NOW,
    )
    body = out.splitlines()
    assert [ln for ln in body if ln in {"HEALTH", "MEMEX", "AGENT", "PROJECTS"}] == [
        "HEALTH",
        "MEMEX",
        "AGENT",
        "PROJECTS",
    ]
    assert SECTION_ORDER == ("health", "vault", "memex", "agent", "projects")


def test_none_sections_are_skipped():
    out = compose_bracket(
        DATE,
        {"health": None, "vault": None, "memex": "M", "agent": "A", "projects": None},
        generated_at=NOW,
    )
    assert "M\n\nA" in out
    assert "None" not in out


def test_generated_at_normalized_to_utc_z():
    pdt = dt.datetime(2026, 6, 11, 0, 51, 1, tzinfo=dt.timezone(dt.timedelta(hours=-7)))
    out = compose_bracket(DATE, {"memex": "M"}, generated_at=pdt)
    assert out.endswith("generated_at=2026-06-11T07:51:01Z -->")


def test_full_mode_is_a_gated_stub():
    with pytest.raises(NotImplementedError, match="step-D"):
        compose_full(DATE, {})


def test_default_daily_post_matches_note_conventions():
    post = default_daily_post(DATE)
    assert post.content == "# check-in — 2026-06-10\n"
    assert post["created"] == "2026-06-10"
    assert post["date"] == "2026-06-10"
    assert post["tags"] == ["journal/checkin"]
