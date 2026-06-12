"""Unit tests for the note writer: bracket strip-and-replace semantics."""

from __future__ import annotations

import datetime as dt

import pytest

from checkin_renderer import note
from checkin_renderer.compose import compose_bracket

DATE = dt.date(2026, 6, 10)


def _bracket(body: str = "## memex — 2026-06-10 — inbox", *, second: int = 1) -> str:
    return compose_bracket(
        DATE,
        {"memex": body},
        generated_at=dt.datetime(2026, 6, 11, 7, 51, second, tzinfo=dt.UTC),
    )


def test_creates_note_with_skeleton_when_absent(settings):
    path = note.write_daily_bracket(DATE, _bracket(), settings=settings)
    assert path == settings.checkin_path(DATE)
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    assert "created: '2026-06-10'" in text
    assert "# check-in — 2026-06-10" in text
    assert "<!-- checkin-renderer:begin daily=2026-06-10 -->" in text
    assert text.rstrip().endswith("-->")


def test_rerun_replaces_bracket_not_appends(settings):
    note.write_daily_bracket(DATE, _bracket("OLD BODY", second=1), settings=settings)
    path = note.write_daily_bracket(DATE, _bracket("NEW BODY", second=2), settings=settings)
    text = path.read_text(encoding="utf-8")
    assert text.count("checkin-renderer:begin daily=2026-06-10") == 1
    assert "OLD BODY" not in text
    assert "NEW BODY" in text


def test_rerun_is_byte_stable_modulo_generated_at(settings):
    p1 = note.write_daily_bracket(DATE, _bracket(second=1), settings=settings)
    first = p1.read_text(encoding="utf-8")
    p2 = note.write_daily_bracket(DATE, _bracket(second=1), settings=settings)
    assert p2.read_text(encoding="utf-8") == first


def test_sibling_markers_and_human_edits_outside_bracket_survive(settings):
    path = settings.checkin_path(DATE)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\n"
        "created: '2026-06-10'\n"
        "date: '2026-06-10'\n"
        "tags:\n"
        "- journal/checkin\n"
        "---\n"
        "\n"
        "# check-in — 2026-06-10\n"
        "\n"
        "## vault-review — 2026-06-10\n"
        "\n"
        "- `~` some file\n"
        "<!-- vault-review:daily=2026-06-10 generated_at=2026-06-11T07:01:01Z -->\n"
        "\n"
        "a human note outside any marker\n",
        encoding="utf-8",
    )
    note.write_daily_bracket(DATE, _bracket(), settings=settings)
    text = path.read_text(encoding="utf-8")
    assert "vault-review:daily=2026-06-10" in text
    assert "a human note outside any marker" in text
    assert "checkin-renderer:begin daily=2026-06-10" in text
    # renderer bracket appended after the existing content
    assert text.index("human note") < text.index("checkin-renderer:begin")


def test_read_daily_bracket_roundtrip(settings):
    assert note.read_daily_bracket(DATE, settings=settings) is None
    note.write_daily_bracket(DATE, _bracket(), settings=settings)
    got = note.read_daily_bracket(DATE, settings=settings)
    assert got is not None
    assert got.startswith("<!-- checkin-renderer:begin daily=2026-06-10 -->")
    assert "## memex — 2026-06-10 — inbox" in got


def test_read_note_returns_none_when_absent(settings):
    assert note.read_note(DATE, settings=settings) is None


def test_write_full_is_a_gated_stub(settings):
    with pytest.raises(NotImplementedError, match="step-D"):
        note.write_full(DATE, "anything", settings=settings)
