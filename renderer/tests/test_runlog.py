"""Unit tests for ops.job_runs recording (separate connection, best-effort)."""

from __future__ import annotations

import datetime as dt

import pytest

from checkin_renderer.runlog import record_best_effort, record_job_run

STARTED = dt.datetime(2026, 6, 11, 7, 51, 0, tzinfo=dt.UTC)


def test_record_job_run_inserts_ok_row(settings, store):
    record_job_run(
        settings,
        started_at=STARTED,
        status="ok",
        summary={"date": "2026-06-10", "mode": "bracket"},
        connect=store.connect,
    )
    assert len(store.job_runs) == 1
    row = store.job_runs[0]
    assert row["job_name"] == "checkin-renderer-daily"
    assert row["host"] == "testhost"
    assert row["started_at"] == STARTED
    assert row["status"] == "ok"
    assert row["summary"] == {"date": "2026-06-10", "mode": "bracket"}


def test_record_job_run_uses_its_own_connection(settings, store):
    before = store.connections_opened
    record_job_run(
        settings, started_at=STARTED, status="ok", summary={}, connect=store.connect
    )
    assert store.connections_opened == before + 1


def test_record_job_run_propagates_failures(settings, store):
    store.fail_connect = True
    with pytest.raises(RuntimeError, match="simulated connect failure"):
        record_job_run(
            settings, started_at=STARTED, status="ok", summary={}, connect=store.connect
        )


def test_record_best_effort_swallows_failures(settings, store):
    store.fail_connect = True
    # must not raise — the original render error wins
    record_best_effort(
        settings,
        started_at=STARTED,
        status="error",
        summary={"error": "boom"},
        connect=store.connect,
    )
    assert store.job_runs == []
