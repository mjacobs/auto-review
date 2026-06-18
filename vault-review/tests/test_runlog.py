"""Unit tests for ops.job_runs recording (auto-review-2vv).

Mirrors renderer/tests/test_runlog.py: separate connection, best-effort error
row, and — vault-review-specific — a NULL cost (no LLM work) plus an explicit
daily/weekly job_name (one CLI process serves both jobs).
"""

from __future__ import annotations

import datetime as dt

import pytest

from vault_review.runlog import SQL_INSERT_JOB_RUN, record_best_effort, record_job_run

STARTED = dt.datetime(2026, 6, 15, 7, 1, 0, tzinfo=dt.UTC)


def test_record_job_run_inserts_ok_row_daily(settings, store):
    record_job_run(
        settings,
        job_name=settings.daily_job_name,
        started_at=STARTED,
        status="ok",
        summary={"date": "2026-06-14", "events": 12, "note_path": "/v/2026-06-14.md"},
        connect=store.connect,
    )
    assert len(store.job_runs) == 1
    row = store.job_runs[0]
    assert row["job_name"] == "vault-review-daily"
    assert row["host"] == "testhost"
    assert row["started_at"] == STARTED
    assert row["status"] == "ok"
    assert row["summary"] == {"date": "2026-06-14", "events": 12, "note_path": "/v/2026-06-14.md"}


def test_record_job_run_weekly_job_name(settings, store):
    record_job_run(
        settings,
        job_name=settings.weekly_job_name,
        started_at=STARTED,
        status="ok",
        summary={"week_label": "2026-W24", "events": 36, "note_path": "/v/2026-W24.md"},
        connect=store.connect,
    )
    assert store.job_runs[0]["job_name"] == "vault-review-weekly"
    assert store.job_runs[0]["summary"]["week_label"] == "2026-W24"


def test_cost_is_always_null(settings, store):
    # vault-review does no LLM work: cost_usd is a hardcoded NULL literal in the
    # INSERT, never a bound param — so the recorded params carry no cost at all.
    record_job_run(
        settings,
        job_name=settings.daily_job_name,
        started_at=STARTED,
        status="ok",
        summary={},
        connect=store.connect,
    )
    assert "cost_usd" not in store.job_runs[0]
    # Belt-and-suspenders: the SQL itself binds NULL, not a %(cost_usd)s param.
    assert "NULL" in SQL_INSERT_JOB_RUN
    assert "%(cost_usd)s" not in SQL_INSERT_JOB_RUN


def test_record_job_run_uses_its_own_connection(settings, store):
    before = store.connections_opened
    record_job_run(
        settings, job_name=settings.daily_job_name, started_at=STARTED,
        status="ok", summary={}, connect=store.connect,
    )
    assert store.connections_opened == before + 1


def test_record_job_run_propagates_failures(settings, store):
    store.fail_connect = True
    with pytest.raises(RuntimeError, match="simulated connect failure"):
        record_job_run(
            settings, job_name=settings.daily_job_name, started_at=STARTED,
            status="ok", summary={}, connect=store.connect,
        )


def test_record_best_effort_swallows_failures(settings, store):
    store.fail_connect = True
    # must not raise — the original section-write error wins
    record_best_effort(
        settings,
        job_name=settings.daily_job_name,
        started_at=STARTED,
        status="error",
        summary={"error": "boom"},
        connect=store.connect,
    )
    assert store.job_runs == []


def test_record_best_effort_records_error_row_on_success(settings, store):
    record_best_effort(
        settings,
        job_name=settings.weekly_job_name,
        started_at=STARTED,
        status="error",
        summary={"week_label": "2026-W24", "error": "RuntimeError: boom"},
        connect=store.connect,
    )
    assert len(store.job_runs) == 1
    assert store.job_runs[0]["status"] == "error"
    assert store.job_runs[0]["job_name"] == "vault-review-weekly"
