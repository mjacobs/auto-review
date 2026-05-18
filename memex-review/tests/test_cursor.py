"""Tests for the cursor state module."""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import yaml

import memex_review.config as config_mod
from memex_review.config import get_settings
from memex_review.cursor import cursor_path, load_cursor, save_cursor


@pytest.fixture(autouse=True)
def isolated_vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("VAULT_PATH", str(tmp_path))
    monkeypatch.setenv("MEMEX_URL", "https://example.invalid")
    monkeypatch.setenv("MEMEX_CLIENT_ID", "id")
    monkeypatch.setenv("MEMEX_CLIENT_SECRET", "secret")
    monkeypatch.setenv("TZ", "America/Los_Angeles")
    monkeypatch.setattr(config_mod, "_settings", None)
    yield tmp_path
    monkeypatch.setattr(config_mod, "_settings", None)


def test_cursor_path_is_under_vault_state(isolated_vault: Path) -> None:
    s = get_settings()
    assert cursor_path(s) == isolated_vault / "state" / "memex-review.yaml"


def test_load_bootstraps_to_today_local_without_writing(isolated_vault: Path) -> None:
    s = get_settings()
    got = load_cursor(s)
    assert got.tzinfo is not None
    assert got.utcoffset() == dt.datetime.now(tz=s.tz).utcoffset()
    today_local = dt.datetime.now(tz=s.tz).date()
    assert got.date() == today_local
    assert (got.hour, got.minute, got.second, got.microsecond) == (0, 0, 0, 0)
    # No file written.
    assert not cursor_path(s).exists()


def test_save_then_load_round_trips(isolated_vault: Path) -> None:
    s = get_settings()
    value = dt.datetime(2026, 5, 17, 23, 59, 59, tzinfo=ZoneInfo("America/Los_Angeles"))
    save_cursor(s, value)
    got = load_cursor(s)
    assert got == value


def test_saved_file_is_human_readable(isolated_vault: Path) -> None:
    s = get_settings()
    value = dt.datetime(2026, 5, 17, 23, 59, 59, tzinfo=ZoneInfo("America/Los_Angeles"))
    save_cursor(s, value)
    text = cursor_path(s).read_text(encoding="utf-8")
    assert "cursor:" in text
    assert "2026-05-17T23:59:59" in text


def test_save_creates_state_dir(isolated_vault: Path) -> None:
    s = get_settings()
    assert not (isolated_vault / "state").exists()
    save_cursor(s, dt.datetime.now(tz=s.tz))
    assert (isolated_vault / "state").is_dir()


def test_save_preserves_future_extension_keys(isolated_vault: Path) -> None:
    s = get_settings()
    path = cursor_path(s)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "cursor: 2026-05-17T23:59:59-07:00\nfuture_key: keep-me\n",
        encoding="utf-8",
    )
    save_cursor(s, dt.datetime(2026, 5, 18, 0, 0, 0, tzinfo=s.tz))
    text = path.read_text(encoding="utf-8")
    assert "future_key" in text
    assert "keep-me" in text
    assert "2026-05-18" in text


def test_corrupt_yaml_raises(isolated_vault: Path) -> None:
    s = get_settings()
    path = cursor_path(s)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("::not yaml::\n  - [bad", encoding="utf-8")
    with pytest.raises(yaml.YAMLError):
        load_cursor(s)


def test_missing_cursor_key_raises(isolated_vault: Path) -> None:
    s = get_settings()
    path = cursor_path(s)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("other_key: value\n", encoding="utf-8")
    with pytest.raises(ValueError, match="cursor"):
        load_cursor(s)


def test_save_rejects_naive_datetime(isolated_vault: Path) -> None:
    s = get_settings()
    with pytest.raises(ValueError, match="tz-aware"):
        save_cursor(s, dt.datetime(2026, 5, 17, 12, 0, 0))


def test_load_rejects_naive_datetime(isolated_vault: Path) -> None:
    s = get_settings()
    path = cursor_path(s)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("cursor: 2026-05-17T23:59:59\n", encoding="utf-8")
    with pytest.raises(ValueError, match="naive"):
        load_cursor(s)


def test_load_normalizes_to_settings_tz(isolated_vault: Path) -> None:
    s = get_settings()
    path = cursor_path(s)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Stored as UTC; should come back in settings tz (America/Los_Angeles).
    path.write_text("cursor: '2026-05-18T06:59:59+00:00'\n", encoding="utf-8")
    got = load_cursor(s)
    assert got == dt.datetime(2026, 5, 17, 23, 59, 59, tzinfo=ZoneInfo("America/Los_Angeles"))
