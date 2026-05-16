"""Tests for vault_review.vault — marker replace-in-place, frontmatter survive."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import frontmatter
import pytest

import vault_review.config as cfg
from vault_review.vault import (
    read_daily_section,
    read_weekly_section,
    remove_daily_section,
    remove_weekly_section,
    write_daily_section,
    write_weekly_section,
)


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path: Path):
    """Point settings at a temp vault so tests never touch ~/vault."""
    s = cfg.Settings(VAULT_PATH=str(tmp_path))
    cfg._settings = s
    yield s
    cfg._settings = None


# ─── daily section ────────────────────────────────────────────────────────────


class TestWriteDailySection:
    def test_creates_file_with_default_frontmatter(self, tmp_path):
        date = dt.date(2026, 5, 14)
        path = write_daily_section(date, "## vault-review — 2026-05-14\n\n_no events_\n")
        assert path.exists()
        post = frontmatter.load(path)
        assert post.get("date") == "2026-05-14"
        assert "journal/checkin" in post.get("tags", [])

    def test_section_appears_in_body(self, tmp_path):
        date = dt.date(2026, 5, 14)
        path = write_daily_section(date, "## vault-review — 2026-05-14\n\n_no events_\n")
        text = path.read_text()
        assert "## vault-review — 2026-05-14" in text
        assert "<!-- vault-review:daily=2026-05-14" in text

    def test_idempotent_no_duplication(self, tmp_path):
        date = dt.date(2026, 5, 14)
        section = "## vault-review — 2026-05-14\n\n_no events_\n"
        write_daily_section(date, section)
        path = write_daily_section(date, section)
        text = path.read_text()
        assert text.count("<!-- vault-review:daily=2026-05-14") == 1

    def test_second_write_replaces_content(self, tmp_path):
        date = dt.date(2026, 5, 14)
        write_daily_section(date, "## vault-review — 2026-05-14\n\n_old content_\n")
        path = write_daily_section(
            date, "## vault-review — 2026-05-14\n\n_new content_\n"
        )
        text = path.read_text()
        assert "_new content_" in text
        assert "_old content_" not in text

    def test_human_edits_outside_section_preserved(self, tmp_path):
        date = dt.date(2026, 5, 14)
        # Write initial section
        path = write_daily_section(date, "## vault-review — 2026-05-14\n\n_v1_\n")
        # Append human content after the section
        path.write_text(
            path.read_text() + "\n## my notes\n\nSome personal notes.\n",
            encoding="utf-8",
        )
        # Re-run vault-review
        write_daily_section(date, "## vault-review — 2026-05-14\n\n_v2_\n")
        text = path.read_text()
        assert "Some personal notes." in text
        assert "_v2_" in text
        assert "_v1_" not in text

    def test_frontmatter_preserved_on_existing_file(self, tmp_path):
        date = dt.date(2026, 5, 14)
        # Pre-create file with custom frontmatter
        note_path = tmp_path / "journal" / "checkins" / "2026-05-14.md"
        note_path.parent.mkdir(parents=True)
        note_path.write_text(
            "---\ncreated: 2026-05-14\ntags:\n- journal/checkin\ncustom_key: preserved\n---\n\n# check-in\n",
            encoding="utf-8",
        )
        write_daily_section(date, "## vault-review — 2026-05-14\n\n_events_\n")
        post = frontmatter.load(note_path)
        assert post.get("custom_key") == "preserved"


class TestReadDailySection:
    def test_returns_none_when_no_file(self, tmp_path):
        assert read_daily_section(dt.date(2026, 5, 1)) is None

    def test_returns_none_when_no_section(self, tmp_path):
        date = dt.date(2026, 5, 14)
        note_path = tmp_path / "journal" / "checkins" / "2026-05-14.md"
        note_path.parent.mkdir(parents=True)
        note_path.write_text("---\n---\n\n# check-in\n", encoding="utf-8")
        assert read_daily_section(date) is None

    def test_returns_section_after_write(self, tmp_path):
        date = dt.date(2026, 5, 14)
        write_daily_section(date, "## vault-review — 2026-05-14\n\n_no events_\n")
        section = read_daily_section(date)
        assert section is not None
        assert "vault-review — 2026-05-14" in section
        assert "<!-- vault-review:daily=2026-05-14" in section


class TestRemoveDailySection:
    def test_returns_false_when_no_file(self, tmp_path):
        assert remove_daily_section(dt.date(2026, 5, 14)) is False

    def test_returns_false_when_no_section(self, tmp_path):
        date = dt.date(2026, 5, 14)
        note_path = tmp_path / "journal" / "checkins" / "2026-05-14.md"
        note_path.parent.mkdir(parents=True)
        note_path.write_text("---\n---\n\n# check-in\n", encoding="utf-8")
        assert remove_daily_section(date) is False

    def test_removes_section_and_returns_true(self, tmp_path):
        date = dt.date(2026, 5, 14)
        write_daily_section(date, "## vault-review — 2026-05-14\n\n_no events_\n")
        assert remove_daily_section(date) is True
        assert read_daily_section(date) is None

    def test_human_content_survives_remove(self, tmp_path):
        date = dt.date(2026, 5, 14)
        path = write_daily_section(date, "## vault-review — 2026-05-14\n\n_events_\n")
        path.write_text(
            path.read_text() + "\n## my notes\n\nPersonal.\n",
            encoding="utf-8",
        )
        remove_daily_section(date)
        text = path.read_text()
        assert "Personal." in text
        assert "<!-- vault-review:daily=2026-05-14" not in text


# ─── weekly section ───────────────────────────────────────────────────────────


class TestWriteWeeklySection:
    def test_creates_file_with_skeleton(self, tmp_path):
        path = write_weekly_section("2026-W20", "## vault-review weekly — 2026-W20\n\n_no events_\n")
        assert path.exists()
        text = path.read_text()
        assert "week of" in text
        assert "projects that moved forward" in text

    def test_marker_present(self, tmp_path):
        path = write_weekly_section("2026-W20", "## vault-review weekly — 2026-W20\n\n_no events_\n")
        text = path.read_text()
        assert "<!-- vault-review:weekly=2026-W20" in text

    def test_idempotent(self, tmp_path):
        section = "## vault-review weekly — 2026-W20\n\n_no events_\n"
        write_weekly_section("2026-W20", section)
        path = write_weekly_section("2026-W20", section)
        text = path.read_text()
        assert text.count("<!-- vault-review:weekly=2026-W20") == 1

    def test_second_write_replaces_content(self, tmp_path):
        write_weekly_section("2026-W20", "## vault-review weekly — 2026-W20\n\n_old_\n")
        path = write_weekly_section("2026-W20", "## vault-review weekly — 2026-W20\n\n_new_\n")
        text = path.read_text()
        assert "_new_" in text
        assert "_old_" not in text


class TestReadWeeklySection:
    def test_returns_none_when_no_file(self, tmp_path):
        assert read_weekly_section("2026-W20") is None

    def test_returns_section_after_write(self, tmp_path):
        write_weekly_section("2026-W20", "## vault-review weekly — 2026-W20\n\n_no events_\n")
        section = read_weekly_section("2026-W20")
        assert section is not None
        assert "<!-- vault-review:weekly=2026-W20" in section


class TestRemoveWeeklySection:
    def test_returns_false_when_no_file(self, tmp_path):
        assert remove_weekly_section("2026-W20") is False

    def test_removes_and_returns_true(self, tmp_path):
        write_weekly_section("2026-W20", "## vault-review weekly — 2026-W20\n\n_no events_\n")
        assert remove_weekly_section("2026-W20") is True
        assert read_weekly_section("2026-W20") is None
