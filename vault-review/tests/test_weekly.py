"""Tests for vault_review.weekly date parsing."""

from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

from vault_review import weekly


class _Settings:
    tz = ZoneInfo("Pacific/Kiritimati")


class _FrozenDateTime(dt.datetime):
    @classmethod
    def now(cls, tz=None):
        instant = dt.datetime(2026, 1, 4, 23, 30, tzinfo=dt.UTC)
        if tz is None:
            return instant.replace(tzinfo=None)
        return instant.astimezone(tz)


def test_parse_week_default_today_uses_configured_timezone(monkeypatch):
    monkeypatch.setattr(weekly, "get_settings", lambda: _Settings())
    monkeypatch.setattr(weekly.dt, "datetime", _FrozenDateTime)

    assert weekly.parse_week("this-week") == "2026-W02"
    assert weekly.parse_week("last-week") == "2026-W01"


def test_parse_week_explicit_today_still_overrides_timezone(monkeypatch):
    monkeypatch.setattr(weekly, "get_settings", lambda: _Settings())
    monkeypatch.setattr(weekly.dt, "datetime", _FrozenDateTime)

    assert weekly.parse_week("this-week", today=dt.date(2026, 1, 4)) == "2026-W01"
