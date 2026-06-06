"""Tests for the append-only inbox writer + frontmatter watermark."""

from __future__ import annotations

import datetime as dt

import frontmatter
import pytest

from memex_triage import inbox
from memex_triage.client import Thought
from memex_triage.config import Settings


@pytest.fixture
def settings(monkeypatch: pytest.MonkeyPatch, tmp_path) -> Settings:
    monkeypatch.setenv("MEMEX_URL", "https://memex.example/api")
    monkeypatch.setenv("MEMEX_CLIENT_ID", "id")
    monkeypatch.setenv("MEMEX_CLIENT_SECRET", "secret")
    monkeypatch.setenv("VAULT_PATH", str(tmp_path))
    monkeypatch.setenv("TZ", "UTC")
    monkeypatch.setenv("INBOX_PATH", "inbox/memex.md")
    return Settings()


def _t(seq: int, *, summary: str | None = None, preview: str = "", tags=()) -> Thought:
    ts = 1_700_000_000_000 + seq * 60_000
    return Thought(
        id=f"{seq:08d}-1111-2222-3333-444444444444",
        seq=seq,
        content_preview=preview,
        source="test",
        summary=summary,
        tags=tuple(tags),
        created_at_ms=ts,
        updated_at_ms=ts,
    )


def test_render_line_shape(settings: Settings) -> None:
    t = _t(5, summary="the retry-loop bug", tags=("debugging", "agent-review"))
    line = inbox.render_line(t, settings.tz)
    assert line.startswith("- [ ] ")
    assert "the retry-loop bug" in line
    assert "`#debugging`" in line and "`#agent-review`" in line
    assert line.endswith("^mx-00000005")


def test_render_line_kebabs_multiword_and_dirty_tags(settings: Settings) -> None:
    t = _t(9, summary="x", tags=("cash investment", "API/v2", "#existing", "Foo Bar!"))
    line = inbox.render_line(t, settings.tz)
    assert "`#cash-investment`" in line
    assert "`#api-v2`" in line
    assert "`#existing`" in line
    assert "`#foo-bar`" in line
    # no raw space-bearing tag leaked through
    assert "#cash investment" not in line


def test_render_line_drops_tags_that_normalize_to_empty(settings: Settings) -> None:
    t = _t(10, summary="x", tags=("good-tag", "!!!", "   ", "another"))
    line = inbox.render_line(t, settings.tz)
    assert "`#good-tag`" in line and "`#another`" in line
    assert "`##" not in line and "`# `" not in line


def test_render_line_falls_back_to_preview(settings: Settings) -> None:
    t = _t(1, summary=None, preview="first line\nsecond line")
    assert "first line" in inbox.render_line(t, settings.tz)
    assert "second line" not in inbox.render_line(t, settings.tz)


def test_init_inbox_sets_watermark(settings: Settings) -> None:
    path = inbox.init_inbox(61, settings=settings)
    assert path.exists()
    post = frontmatter.load(path)
    assert post.metadata["last_seq"] == 61
    assert inbox.count_task_lines(settings) == 0


def test_init_inbox_refuses_to_clobber(settings: Settings) -> None:
    inbox.init_inbox(1, settings=settings)
    with pytest.raises(FileExistsError):
        inbox.init_inbox(2, settings=settings)


def test_append_advances_watermark_and_appends_lines(settings: Settings) -> None:
    inbox.init_inbox(0, settings=settings)
    n = inbox.append_thoughts([_t(1), _t(2), _t(3)], settings=settings)
    assert n == 3
    assert inbox.load_last_seq(settings) == 3
    assert inbox.count_task_lines(settings) == 3


def test_append_is_idempotent_below_watermark(settings: Settings) -> None:
    inbox.init_inbox(0, settings=settings)
    inbox.append_thoughts([_t(1), _t(2)], settings=settings)
    # Re-delivering the same (or older) seqs appends nothing.
    n = inbox.append_thoughts([_t(1), _t(2)], settings=settings)
    assert n == 0
    assert inbox.count_task_lines(settings) == 2
    assert inbox.load_last_seq(settings) == 2


def test_append_only_new_when_batch_overlaps(settings: Settings) -> None:
    inbox.init_inbox(0, settings=settings)
    inbox.append_thoughts([_t(1), _t(2)], settings=settings)
    n = inbox.append_thoughts([_t(2), _t(3), _t(4)], settings=settings)
    assert n == 2  # only 3 and 4 are new
    assert inbox.load_last_seq(settings) == 4
    assert inbox.count_task_lines(settings) == 4


def test_append_preserves_human_edits(settings: Settings) -> None:
    inbox.init_inbox(0, settings=settings)
    inbox.append_thoughts([_t(1)], settings=settings)
    # Human deletes the delivered line and adds their own note.
    path = settings.inbox_file
    post = frontmatter.load(path)
    post.content = post.content.replace("- [ ] ", "MY NOTE ", 1)
    path.write_text(frontmatter.dumps(post) + "\n", encoding="utf-8")

    inbox.append_thoughts([_t(2)], settings=settings)
    body = frontmatter.load(path).content
    assert "MY NOTE" in body  # untouched
    assert "^mx-00000002" in body  # new line landed


def test_append_to_missing_file_creates_it(settings: Settings) -> None:
    # No init: append onto a non-existent inbox (watermark unset → all delivered).
    assert not settings.inbox_file.exists()
    n = inbox.append_thoughts([_t(7), _t(8)], settings=settings)
    assert n == 2
    assert inbox.load_last_seq(settings) == 8


def test_append_uses_injected_now(settings: Settings) -> None:
    inbox.init_inbox(0, settings=settings)
    when = dt.datetime(2026, 6, 5, 12, 0, tzinfo=dt.UTC)
    inbox.append_thoughts([_t(1)], settings=settings, now=when)
    post = frontmatter.load(settings.inbox_file)
    assert post.metadata["last_synced_at"].startswith("2026-06-05T12:00:00")
