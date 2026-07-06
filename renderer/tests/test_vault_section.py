"""Unit tests for the vault-review section (port of vault-review's dossier).

hg6.7 / step C: the renderer formats vault_review.daily_digests.events instead
of vault-review writing its own marker section.
"""

from __future__ import annotations

import datetime as dt

from checkin_renderer.queries import VaultDigestRow
from checkin_renderer.sections.vault import render_vault_section

DATE = dt.date(2026, 6, 10)


def _digest(events: list[dict]) -> VaultDigestRow:
    return VaultDigestRow(
        digest_date=DATE,
        window_start=dt.datetime(2026, 6, 10, 7, tzinfo=dt.UTC),
        window_end=dt.datetime(2026, 6, 11, 7, tzinfo=dt.UTC),
        events=tuple(events),
    )


def test_missing_row_renders_placeholder():
    out = render_vault_section(None, DATE)
    assert out == "## vault-review — 2026-06-10\n\n_no vault digest row for 2026-06-10_"


def test_empty_events_renders_no_changes():
    out = render_vault_section(_digest([]), DATE)
    assert "## vault-review — 2026-06-10" in out
    assert "_window: 2026-06-10_" in out
    assert "_no authored changes in window_" in out


def test_prefixes_and_summaries():
    out = render_vault_section(
        _digest(
            [
                {"status": "A", "path": "notes/a.md", "renamed_from": None,
                 "group": "notes", "summary": "new note"},
                {"status": "M", "path": "notes/b.md", "renamed_from": None,
                 "group": "notes", "summary": "edited"},
                {"status": "D", "path": "notes/c.md", "renamed_from": None,
                 "group": "notes", "summary": None},
                {"status": "R100", "path": "notes/new.md", "renamed_from": "notes/old.md",
                 "group": "notes", "summary": None},
            ]
        ),
        DATE,
    )
    assert "- `+` `notes/a.md` — new note" in out
    assert "- `~` `notes/b.md` — edited" in out
    assert "- `-` `notes/c.md`" in out
    assert "- `↻` `notes/new.md` (renamed from `notes/old.md`)" in out


def test_groups_sorted_alphabetically():
    out = render_vault_section(
        _digest(
            [
                {"status": "M", "path": "zzz/z.md", "renamed_from": None,
                 "group": "zzz", "summary": "z"},
                {"status": "M", "path": "aaa/a.md", "renamed_from": None,
                 "group": "aaa", "summary": "a"},
            ]
        ),
        DATE,
    )
    assert out.index("### aaa") < out.index("### zzz")


def test_no_trailing_newline():
    # Compose strips section newlines, but keep the sibling contract (no
    # trailing newline) so assembly stays predictable.
    out = render_vault_section(
        _digest(
            [{"status": "M", "path": "n.md", "renamed_from": None,
              "group": "(root)", "summary": "x"}]
        ),
        DATE,
    )
    assert not out.endswith("\n")
