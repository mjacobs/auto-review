"""Tests for the marker-bracketed vault writer."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

import memex_review.config as config_mod
from memex_review.vault import read_daily_section, remove_daily_section, write_daily_section


@pytest.fixture(autouse=True)
def isolated_vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Point Settings at a temp vault and reset the get_settings() cache."""
    monkeypatch.setenv("VAULT_PATH", str(tmp_path))
    monkeypatch.setenv("MEMEX_URL", "https://example.invalid")
    monkeypatch.setenv("MEMEX_CLIENT_ID", "id")
    monkeypatch.setenv("MEMEX_CLIENT_SECRET", "secret")
    monkeypatch.setattr(config_mod, "_settings", None)
    yield tmp_path
    monkeypatch.setattr(config_mod, "_settings", None)


DATE = dt.date(2026, 5, 14)
SECTION = (
    "## memex-review — 2026-05-14 — inbox\n"
    "\n"
    "_window: 2026-05-14 — 1 capture_\n"
    "\n"
    "- 09:00 — hello `[#x]`\n"
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_write_creates_note_with_default_frontmatter(isolated_vault: Path) -> None:
    path = write_daily_section(DATE, SECTION)
    assert path.exists()
    text = _read(path)
    assert text.startswith("---\n")  # frontmatter present
    assert "tags:\n- journal/checkin" in text
    assert "## memex-review — 2026-05-14 — inbox" in text
    assert "<!-- memex-review:daily=2026-05-14 generated_at=" in text


def test_write_is_idempotent(isolated_vault: Path) -> None:
    write_daily_section(DATE, SECTION)
    first = _read(write_daily_section(DATE, SECTION))
    # Two writes should leave exactly one section.
    assert first.count("## memex-review — 2026-05-14") == 1
    assert first.count("<!-- memex-review:daily=2026-05-14") == 1


def test_write_replaces_existing_section_with_new_content(isolated_vault: Path) -> None:
    write_daily_section(DATE, SECTION)
    new_section = SECTION.replace("hello", "world")
    path = write_daily_section(DATE, new_section)
    text = _read(path)
    assert "world" in text
    assert "hello" not in text


def test_write_preserves_human_edits_outside_marker(isolated_vault: Path) -> None:
    path = write_daily_section(DATE, SECTION)
    # Simulate a hand edit before the section.
    text = _read(path)
    edited = text.replace(
        "## memex-review",
        "## morning notes\nslept well, coffee strong.\n\n## memex-review",
        1,
    )
    path.write_text(edited, encoding="utf-8")

    # Re-running must keep the human edit.
    write_daily_section(DATE, SECTION.replace("hello", "world"))
    text2 = _read(path)
    assert "slept well, coffee strong." in text2
    assert "world" in text2
    assert "hello" not in text2


def test_write_preserves_frontmatter_keys(isolated_vault: Path) -> None:
    path = write_daily_section(DATE, SECTION)
    # Inject a custom frontmatter key.
    import frontmatter

    post = frontmatter.load(path)
    post["mood"] = "focused"
    path.write_text(frontmatter.dumps(post) + "\n", encoding="utf-8")

    write_daily_section(DATE, SECTION.replace("hello", "world"))
    post2 = frontmatter.load(path)
    assert post2.get("mood") == "focused"
    assert post2.get("tags") == ["journal/checkin"]


def test_read_returns_section_or_none(isolated_vault: Path) -> None:
    assert read_daily_section(DATE) is None
    write_daily_section(DATE, SECTION)
    got = read_daily_section(DATE)
    assert got is not None
    assert got.startswith("## memex-review — 2026-05-14")
    assert got.rstrip().endswith("-->")


def test_remove_returns_false_when_missing(isolated_vault: Path) -> None:
    assert remove_daily_section(DATE) is False  # no note at all
    # Note exists but no section yet:
    write_daily_section(DATE, SECTION)
    remove_daily_section(DATE)
    assert remove_daily_section(DATE) is False


def test_remove_strips_section_only(isolated_vault: Path) -> None:
    path = write_daily_section(DATE, SECTION)
    # Add a human edit.
    text = _read(path)
    path.write_text(text + "\n## evening notes\nsaw deer at dusk.\n", encoding="utf-8")

    assert remove_daily_section(DATE) is True
    text2 = _read(path)
    assert "## memex-review" not in text2
    assert "<!-- memex-review:daily=2026-05-14" not in text2
    assert "saw deer at dusk." in text2


def test_write_only_touches_target_date_section(isolated_vault: Path) -> None:
    """A prior date's section must survive a write for a different date."""
    earlier = dt.date(2026, 5, 13)
    write_daily_section(earlier, SECTION.replace("2026-05-14", "2026-05-13"))
    write_daily_section(DATE, SECTION)
    # Different notes:
    earlier_path = isolated_vault / "journal" / "checkins" / "2026" / "05" / "2026-05-13.md"
    today_path = isolated_vault / "journal" / "checkins" / "2026" / "05" / "2026-05-14.md"
    assert "## memex-review — 2026-05-13" in _read(earlier_path)
    assert "## memex-review — 2026-05-14" in _read(today_path)


def test_write_only_touches_own_section_when_others_present(isolated_vault: Path) -> None:
    """A sibling tool's section (e.g. vault-review) must survive our write."""
    path = isolated_vault / "journal" / "checkins" / "2026" / "05" / "2026-05-14.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\ndate: 2026-05-14\n---\n\n"
        "## vault-review — 2026-05-14\n\n_window: 2026-05-14_\n\n"
        "<!-- vault-review:daily=2026-05-14 generated_at=2026-05-15T00:00:00Z -->\n",
        encoding="utf-8",
    )

    write_daily_section(DATE, SECTION)
    text = _read(path)
    assert "## vault-review — 2026-05-14" in text
    assert "<!-- vault-review:daily=2026-05-14" in text
    assert "## memex-review — 2026-05-14" in text
    assert "<!-- memex-review:daily=2026-05-14" in text
