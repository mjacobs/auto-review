"""Tests for `process` and `cursor` CLI verbs (auto-review-a4w)."""

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
from memex_review.cursor import cursor_path, load_cursor, save_cursor

LA = ZoneInfo("America/Los_Angeles")


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


def _yest_iso() -> str:
    return (dt.datetime.now(tz=LA).date() - dt.timedelta(days=1)).isoformat()


def _tomorrow_iso() -> str:
    return (dt.datetime.now(tz=LA).date() + dt.timedelta(days=1)).isoformat()


# --- process ---------------------------------------------------------------


def test_process_bootstraps_then_advances() -> None:
    s = get_settings()
    assert not cursor_path(s).exists()
    r = CliRunner().invoke(main, ["process"])
    assert r.exit_code == 0, r.output
    assert cursor_path(s).exists()
    cursor = load_cursor(s)
    yest = dt.datetime.now(tz=LA).date() - dt.timedelta(days=1)
    assert cursor.date() == yest
    assert (cursor.hour, cursor.minute, cursor.second) == (23, 59, 59)


def test_process_twice_is_noop() -> None:
    s = get_settings()
    r1 = CliRunner().invoke(main, ["process"])
    assert r1.exit_code == 0
    first = load_cursor(s)
    r2 = CliRunner().invoke(main, ["process"])
    assert r2.exit_code == 0, r2.output
    assert "already at or past" in r2.stderr if r2.stderr else "already at or past" in r2.output
    assert load_cursor(s) == first


def test_process_refuses_future() -> None:
    r = CliRunner().invoke(main, ["process", "--through", _tomorrow_iso()])
    assert r.exit_code == 2
    s = get_settings()
    assert not cursor_path(s).exists()


def test_process_refuses_today() -> None:
    today = dt.datetime.now(tz=LA).date().isoformat()
    r = CliRunner().invoke(main, ["process", "--through", today])
    assert r.exit_code == 2


def test_process_through_explicit_yesterday() -> None:
    r = CliRunner().invoke(main, ["process", "--through", _yest_iso()])
    assert r.exit_code == 0, r.output
    s = get_settings()
    assert load_cursor(s).date() == dt.datetime.now(tz=LA).date() - dt.timedelta(days=1)


# --- cursor (read) ---------------------------------------------------------


def test_cursor_show_when_unset_notes_not_persisted() -> None:
    r = CliRunner().invoke(main, ["cursor"])
    assert r.exit_code == 0, r.output
    assert "not yet persisted" in r.output


def test_cursor_show_when_set_omits_persistence_note() -> None:
    s = get_settings()
    save_cursor(s, dt.datetime(2026, 5, 17, 23, 59, 59, tzinfo=LA))
    r = CliRunner().invoke(main, ["cursor"])
    assert r.exit_code == 0, r.output
    assert "2026-05-17T23:59:59" in r.output
    assert "not yet persisted" not in r.output


# --- cursor --rewind -------------------------------------------------------


def test_cursor_rewind_to_past_succeeds() -> None:
    s = get_settings()
    save_cursor(s, dt.datetime(2026, 5, 17, 23, 59, 59, tzinfo=LA))
    r = CliRunner().invoke(main, ["cursor", "--rewind", "2026-05-10"])
    assert r.exit_code == 0, r.output
    got = load_cursor(s)
    assert got.date() == dt.date(2026, 5, 10)


def test_cursor_rewind_forward_refused() -> None:
    s = get_settings()
    save_cursor(s, dt.datetime(2026, 5, 10, 23, 59, 59, tzinfo=LA))
    r = CliRunner().invoke(main, ["cursor", "--rewind", "2026-05-17"])
    assert r.exit_code == 2
    assert load_cursor(s).date() == dt.date(2026, 5, 10)


# --- cursor --init ---------------------------------------------------------


def test_cursor_init_when_file_missing_succeeds() -> None:
    s = get_settings()
    r = CliRunner().invoke(main, ["cursor", "--init", "2026-04-01"])
    assert r.exit_code == 0, r.output
    assert load_cursor(s).date() == dt.date(2026, 4, 1)


def test_cursor_init_when_file_exists_refused() -> None:
    s = get_settings()
    save_cursor(s, dt.datetime(2026, 5, 17, 23, 59, 59, tzinfo=LA))
    r = CliRunner().invoke(main, ["cursor", "--init", "2026-04-01"])
    assert r.exit_code == 2
    assert load_cursor(s).date() == dt.date(2026, 5, 17)


def test_cursor_init_and_rewind_mutually_exclusive() -> None:
    r = CliRunner().invoke(main, ["cursor", "--init", "2026-04-01", "--rewind", "2026-04-02"])
    assert r.exit_code == 2


# --- integration: process advance hides captures from `run` ----------------


def test_process_advance_hides_prior_captures_from_run(monkeypatch: pytest.MonkeyPatch) -> None:
    yest = dt.datetime.now(tz=LA).date() - dt.timedelta(days=1)
    yest_ms = int(dt.datetime.combine(yest, dt.time(10, 0), tzinfo=LA).timestamp() * 1000)
    captures = [
        Thought(
            id="y1",
            content_preview="",
            source=None,
            summary="yest-cap",
            tags=(),
            created_at_ms=yest_ms,
            updated_at_ms=yest_ms,
        )
    ]
    monkeypatch.setattr(cli_mod, "collect_for_date", lambda date, settings: captures)

    # Before advancing: rewind cursor to before yesterday so the capture is visible.
    s = get_settings()
    save_cursor(s, dt.datetime(2026, 1, 1, 0, 0, 0, tzinfo=LA))
    r_before = CliRunner().invoke(main, ["run", yest.isoformat(), "--dry-run", "--print"])
    assert r_before.exit_code == 0
    assert "yest-cap" in r_before.output

    # Advance through yesterday.
    r_adv = CliRunner().invoke(main, ["process"])
    assert r_adv.exit_code == 0, r_adv.output

    # After advancing, yesterday's capture is hidden.
    r_after = CliRunner().invoke(main, ["run", yest.isoformat(), "--dry-run", "--print"])
    assert r_after.exit_code == 0
    assert "yest-cap" not in r_after.output
    assert "_no captures in window_" in r_after.output
