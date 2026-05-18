"""Tests for cursor-aware render filtering (auto-review-uwr)."""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from click.testing import CliRunner

import memex_review.cli as cli_mod
import memex_review.config as config_mod
from memex_review.cli import main
from memex_review.client import Thought
from memex_review.config import get_settings
from memex_review.cursor import filter_visible, save_cursor

LA = ZoneInfo("America/Los_Angeles")


def _t(ts_iso: str, *, id_: str | None = None) -> Thought:
    when = dt.datetime.fromisoformat(ts_iso)
    if when.tzinfo is None:
        when = when.replace(tzinfo=dt.timezone.utc)
    ms = int(when.timestamp() * 1000)
    return Thought(
        id=id_ or f"id-{ts_iso}",
        content_preview="",
        source=None,
        summary="s",
        tags=(),
        created_at_ms=ms,
        updated_at_ms=ms,
    )


@pytest.fixture(autouse=True)
def isolated_vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("VAULT_PATH", str(tmp_path))
    monkeypatch.setenv("MEMEX_URL", "https://example.invalid")
    monkeypatch.setenv("MEMEX_CLIENT_ID", "id")
    monkeypatch.setenv("MEMEX_CLIENT_SECRET", "secret")
    monkeypatch.setenv("TZ", "America/Los_Angeles")
    monkeypatch.setattr(config_mod, "_settings", None)
    (tmp_path / "journal" / "checkins").mkdir(parents=True)
    yield tmp_path
    monkeypatch.setattr(config_mod, "_settings", None)


def test_filter_visible_drops_before_cursor() -> None:
    cursor = dt.datetime(2026, 5, 17, 12, 0, 0, tzinfo=LA)
    early = _t("2026-05-17T10:00:00-07:00", id_="early")
    at = _t("2026-05-17T12:00:00-07:00", id_="at")
    later = _t("2026-05-17T15:00:00-07:00", id_="later")
    out = filter_visible([early, at, later], cursor)
    ids = {t.id for t in out}
    assert ids == {"at", "later"}


def test_filter_visible_rejects_naive_cursor() -> None:
    with pytest.raises(ValueError, match="tz-aware"):
        filter_visible([], dt.datetime(2026, 5, 17, 12, 0, 0))


def test_run_with_cursor_in_future_renders_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    s = get_settings()
    # Captures all in early morning.
    thoughts = [_t("2026-05-17T15:00:00", id_="morning")]  # 08:00 PDT
    monkeypatch.setattr(cli_mod, "collect_for_date", lambda date, settings: thoughts)
    save_cursor(s, dt.datetime(2026, 5, 17, 23, 59, 59, tzinfo=LA))

    result = CliRunner().invoke(main, ["run", "2026-05-17", "--dry-run", "--print"])
    assert result.exit_code == 0, result.output
    assert "_no captures in window_" in result.output
    assert "_window: 2026-05-17 — 0 captures_" in result.output


def test_run_with_cursor_in_past_renders_all(monkeypatch: pytest.MonkeyPatch) -> None:
    s = get_settings()
    thoughts = [
        _t("2026-05-17T15:00:00", id_="a"),
        _t("2026-05-17T20:00:00", id_="b"),
    ]
    monkeypatch.setattr(cli_mod, "collect_for_date", lambda date, settings: thoughts)
    save_cursor(s, dt.datetime(2026, 5, 1, 0, 0, 0, tzinfo=LA))

    result = CliRunner().invoke(main, ["run", "2026-05-17", "--dry-run", "--print"])
    assert result.exit_code == 0, result.output
    assert "_window: 2026-05-17 — 2 captures_" in result.output


def test_run_for_past_date_below_cursor_renders_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    s = get_settings()
    thoughts = [_t("2026-05-10T15:00:00", id_="old")]
    monkeypatch.setattr(cli_mod, "collect_for_date", lambda date, settings: thoughts)
    save_cursor(s, dt.datetime(2026, 5, 15, 0, 0, 0, tzinfo=LA))

    result = CliRunner().invoke(main, ["run", "2026-05-10", "--dry-run", "--print"])
    assert result.exit_code == 0, result.output
    assert "_no captures in window_" in result.output


def test_run_bootstrap_hides_pre_today_shows_today(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No cursor file → bootstrap = today 00:00 local; today's captures show, prior days hide."""
    today_local = dt.datetime.now(tz=LA).date()
    today_iso = today_local.isoformat()

    todays = [
        Thought(
            id="t1",
            content_preview="",
            source=None,
            summary="today-cap",
            tags=(),
            created_at_ms=int(
                dt.datetime.combine(today_local, dt.time(10, 0), tzinfo=LA).timestamp() * 1000
            ),
            updated_at_ms=0,
        )
    ]
    yest = today_local - dt.timedelta(days=1)
    yesterdays = [
        Thought(
            id="y1",
            content_preview="",
            source=None,
            summary="yest-cap",
            tags=(),
            created_at_ms=int(
                dt.datetime.combine(yest, dt.time(10, 0), tzinfo=LA).timestamp() * 1000
            ),
            updated_at_ms=0,
        )
    ]

    def fake_collect(date, settings):
        return todays if date == today_local else yesterdays

    monkeypatch.setattr(cli_mod, "collect_for_date", fake_collect)

    r1 = CliRunner().invoke(main, ["run", today_iso, "--dry-run", "--print"])
    assert r1.exit_code == 0, r1.output
    assert "today-cap" in r1.output
    assert f"_window: {today_iso} — 1 capture_" in r1.output

    r2 = CliRunner().invoke(main, ["run", yest.isoformat(), "--dry-run", "--print"])
    assert r2.exit_code == 0, r2.output
    assert "yest-cap" not in r2.output
    assert "_no captures in window_" in r2.output
