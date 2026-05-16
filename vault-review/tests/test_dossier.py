"""Tests for vault_review.dossier — render_dossier and helpers."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from vault_review.dossier import group_of, render_dossier, summarize_file


# ─── group_of ────────────────────────────────────────────────────────────────


class TestGroupOf:
    def test_journal_top_level(self):
        assert group_of("journal/checkins/2026-05-14.md") == "journal"

    def test_projects_nested(self):
        assert group_of("projects/foo/bar.md") == "projects/foo"

    def test_projects_deeply_nested(self):
        assert group_of("projects/foo/baz/qux.md") == "projects/foo"

    def test_root_level_file(self):
        assert group_of("README.md") == "(root)"

    def test_single_directory(self):
        assert group_of("notes/something.md") == "notes"

    def test_projects_missing_subfolder(self):
        # projects/foo.md — only 2 parts, no subfolder
        assert group_of("projects/foo.md") == "projects"


# ─── summarize_file ──────────────────────────────────────────────────────────


class TestSummarizeFile:
    def test_missing_file_returns_placeholder(self, tmp_path):
        assert summarize_file(tmp_path, "nonexistent.md") == "(no longer present)"

    def test_empty_file_returns_empty(self, tmp_path):
        p = tmp_path / "empty.md"
        p.write_text("", encoding="utf-8")
        assert summarize_file(tmp_path, "empty.md") == "(empty)"

    def test_frontmatter_description_preferred(self, tmp_path):
        p = tmp_path / "note.md"
        p.write_text(
            "---\ndescription: The canonical description\n---\n\n# Heading\n\nBody.\n",
            encoding="utf-8",
        )
        assert summarize_file(tmp_path, "note.md") == "The canonical description"

    def test_heading_plus_body_fallback(self, tmp_path):
        p = tmp_path / "note.md"
        p.write_text("# My Heading\n\nFirst paragraph here.\n", encoding="utf-8")
        result = summarize_file(tmp_path, "note.md")
        assert "My Heading" in result
        assert "First paragraph here." in result

    def test_heading_only_no_body(self, tmp_path):
        p = tmp_path / "note.md"
        p.write_text("# Only a Heading\n", encoding="utf-8")
        assert summarize_file(tmp_path, "note.md") == "Only a Heading"

    def test_no_heading_returns_first_line(self, tmp_path):
        p = tmp_path / "note.md"
        p.write_text("Just a plain line.\n", encoding="utf-8")
        assert summarize_file(tmp_path, "note.md") == "Just a plain line."

    def test_frontmatter_without_description_uses_heading(self, tmp_path):
        p = tmp_path / "note.md"
        p.write_text(
            "---\ntags:\n- foo\n---\n\n# The Heading\n\nSome body.\n",
            encoding="utf-8",
        )
        result = summarize_file(tmp_path, "note.md")
        assert "The Heading" in result


# ─── render_dossier ──────────────────────────────────────────────────────────


class TestRenderDossier:
    def test_empty_events_renders_no_changes_message(self, tmp_path):
        result = render_dossier(tmp_path, [], "2026-05-14", "vault-review — 2026-05-14")
        assert "no authored changes in window" in result
        assert "## vault-review — 2026-05-14" in result
        assert "_window: 2026-05-14_" in result

    def test_added_file_shows_plus_prefix(self, tmp_path):
        p = tmp_path / "note.md"
        p.write_text("# New Note\n\nContent.\n", encoding="utf-8")
        events = [("A", "note.md", None)]
        result = render_dossier(tmp_path, events, "2026-05-14", "vault-review — 2026-05-14")
        assert "`+`" in result
        assert "`note.md`" in result

    def test_modified_file_shows_tilde_prefix(self, tmp_path):
        p = tmp_path / "note.md"
        p.write_text("# Modified\n\nContent.\n", encoding="utf-8")
        events = [("M", "note.md", None)]
        result = render_dossier(tmp_path, events, "2026-05-14", "vault-review — 2026-05-14")
        assert "`~`" in result

    def test_deleted_file_shows_minus_prefix(self, tmp_path):
        events = [("D", "deleted.md", None)]
        result = render_dossier(tmp_path, events, "2026-05-14", "vault-review — 2026-05-14")
        assert "`-`" in result
        assert "`deleted.md`" in result

    def test_renamed_file_shows_arrow_prefix(self, tmp_path):
        p = tmp_path / "new_name.md"
        p.write_text("# Renamed\n", encoding="utf-8")
        events = [("R100", "old_name.md", "new_name.md")]
        result = render_dossier(tmp_path, events, "2026-05-14", "vault-review — 2026-05-14")
        assert "`↻`" in result
        assert "`new_name.md`" in result
        assert "`old_name.md`" in result

    def test_events_grouped_by_directory(self, tmp_path):
        (tmp_path / "journal").mkdir()
        (tmp_path / "projects" / "foo").mkdir(parents=True)
        (tmp_path / "journal" / "note.md").write_text("# J\n", encoding="utf-8")
        (tmp_path / "projects" / "foo" / "bar.md").write_text("# P\n", encoding="utf-8")
        events = [
            ("A", "journal/note.md", None),
            ("M", "projects/foo/bar.md", None),
        ]
        result = render_dossier(tmp_path, events, "2026-05-14", "vault-review — 2026-05-14")
        assert "### journal" in result
        assert "### projects/foo" in result

    def test_groups_sorted_alphabetically(self, tmp_path):
        (tmp_path / "z_dir").mkdir()
        (tmp_path / "a_dir").mkdir()
        (tmp_path / "z_dir" / "n.md").write_text("# Z\n", encoding="utf-8")
        (tmp_path / "a_dir" / "n.md").write_text("# A\n", encoding="utf-8")
        events = [
            ("A", "z_dir/n.md", None),
            ("A", "a_dir/n.md", None),
        ]
        result = render_dossier(tmp_path, events, "2026-05-14", "vault-review — 2026-05-14")
        a_pos = result.index("### a_dir")
        z_pos = result.index("### z_dir")
        assert a_pos < z_pos

    def test_heading_and_window_label_in_output(self, tmp_path):
        result = render_dossier(
            tmp_path, [], "7d (2026-W20)", "vault-review weekly — 2026-W20"
        )
        assert "## vault-review weekly — 2026-W20" in result
        assert "_window: 7d (2026-W20)_" in result

    def test_snapshot_single_add(self, tmp_path):
        (tmp_path / "notes").mkdir()
        (tmp_path / "notes" / "idea.md").write_text(
            "---\ndescription: A great idea\n---\n\n# Idea\n",
            encoding="utf-8",
        )
        events = [("A", "notes/idea.md", None)]
        result = render_dossier(tmp_path, events, "2026-05-14", "vault-review — 2026-05-14")
        expected_lines = [
            "## vault-review — 2026-05-14",
            "_window: 2026-05-14_",
            "### notes",
            "- `+` `notes/idea.md` — A great idea",
        ]
        for line in expected_lines:
            assert line in result, f"missing line: {line!r}"
