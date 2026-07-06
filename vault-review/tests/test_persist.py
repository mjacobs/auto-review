"""Unit tests for vault_review digest-row persistence (auto-review-hg6.7).

Mirrors test_runlog: a fake connect() seam (conftest `store`) records the
UPSERT params so the record logic is exercised without a live DB. Covers the
optional-DSN guard and that a persist failure propagates (loud, unlike runlog's
best-effort error row).
"""

from __future__ import annotations

import datetime as dt

import pytest

from vault_review import config
from vault_review.persist import (
    SQL_UPSERT_DAILY,
    SQL_UPSERT_WEEKLY,
    persist_daily,
    persist_weekly,
)

WSTART = dt.datetime(2026, 6, 14, 7, 0, tzinfo=dt.UTC)
WEND = dt.datetime(2026, 6, 15, 7, 0, tzinfo=dt.UTC)
EVENTS = [
    {"status": "M", "path": "projects/x/n.md", "renamed_from": None,
     "group": "projects/x", "summary": "did a thing"},
    {"status": "A", "path": "notes/y.md", "renamed_from": None,
     "group": "notes", "summary": "new note"},
]


def test_persist_daily_upserts_row(settings, store):
    wrote = persist_daily(
        settings,
        digest_date=dt.date(2026, 6, 14),
        window_start=WSTART,
        window_end=WEND,
        events=EVENTS,
        connect=store.connect,
    )
    assert wrote is True
    assert len(store.daily_digests) == 1
    row = store.daily_digests[0]
    assert row["digest_date"] == dt.date(2026, 6, 14)
    assert row["window_start"] == WSTART
    assert row["window_end"] == WEND
    assert row["events"] == EVENTS  # round-tripped through json


def test_persist_weekly_upserts_row(settings, store):
    wrote = persist_weekly(
        settings,
        week_label="2026-W24",
        window_start=WSTART,
        window_end=WEND,
        events=EVENTS,
        connect=store.connect,
    )
    assert wrote is True
    assert len(store.weekly_digests) == 1
    assert store.weekly_digests[0]["week_label"] == "2026-W24"
    assert store.weekly_digests[0]["events"] == EVENTS


def test_persist_uses_its_own_connection(settings, store):
    before = store.connections_opened
    persist_daily(
        settings,
        digest_date=dt.date(2026, 6, 14),
        window_start=WSTART,
        window_end=WEND,
        events=EVENTS,
        connect=store.connect,
    )
    assert store.connections_opened == before + 1


def test_upsert_sql_is_idempotent_on_conflict():
    # The store is the source of truth; a re-run for the same key must replace,
    # not error or duplicate — the daily note is regenerable at any time.
    assert "ON CONFLICT (digest_date) DO UPDATE" in SQL_UPSERT_DAILY
    assert "ON CONFLICT (week_label) DO UPDATE" in SQL_UPSERT_WEEKLY


def test_persist_failure_propagates(settings, store):
    # Unlike runlog.record_best_effort, a failed persist is a real run failure
    # (the row IS the store) — it must NOT be swallowed (OMG-003 lesson).
    store.fail_connect = True
    with pytest.raises(RuntimeError, match="simulated connect failure"):
        persist_daily(
            settings,
            digest_date=dt.date(2026, 6, 14),
            window_start=WSTART,
            window_end=WEND,
            events=EVENTS,
            connect=store.connect,
        )


def test_no_dsn_skips_persist(monkeypatch, tmp_path, store):
    # PG liveness is optional: a manual / no-PG run writes its markdown and
    # persists nothing (returns False), same optionality as runlog.
    monkeypatch.delenv("VAULT_REVIEW_PG_DSN", raising=False)
    monkeypatch.setenv("VAULT_PATH", str(tmp_path / "vault"))
    monkeypatch.setattr(config, "_settings", None)
    no_dsn = config.get_settings()
    assert no_dsn.pg_dsn is None

    wrote = persist_daily(
        no_dsn,
        digest_date=dt.date(2026, 6, 14),
        window_start=WSTART,
        window_end=WEND,
        events=EVENTS,
        connect=store.connect,
    )
    assert wrote is False
    assert store.daily_digests == []
