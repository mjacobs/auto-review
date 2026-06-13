"""Tests for ops.job_runs recording (auto-review-hg6.8).

agent-review has no shared FakeStore, so this builds a minimal fake connection
inline. record_job_run/record_best_effort only read settings.job_name +
settings.host and the injected connect() seam, so a SimpleNamespace stands in
for Settings (which otherwise demands PG_DSN/LLM_API_KEY env).
"""

from __future__ import annotations

import datetime as dt
import json
from types import SimpleNamespace

import pytest

from agent_review.runlog import SQL_INSERT_JOB_RUN, record_best_effort, record_job_run

STARTED = dt.datetime(2026, 6, 12, 7, 21, 0, tzinfo=dt.UTC)


class _FakeCursor:
    def __init__(self, store: _FakeStore) -> None:
        self.store = store

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, *exc) -> None:
        return None

    def execute(self, sql: str, params: dict) -> None:
        assert sql == SQL_INSERT_JOB_RUN
        row = dict(params)
        row["summary"] = json.loads(row["summary"])
        self.store.job_runs.append(row)


class _FakeConn:
    def __init__(self, store: _FakeStore) -> None:
        self.store = store

    def __enter__(self) -> _FakeConn:
        return self

    def __exit__(self, *exc) -> None:
        return None

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self.store)


class _FakeStore:
    def __init__(self) -> None:
        self.job_runs: list[dict] = []
        self.connections_opened = 0
        self.fail_connect = False

    def connect(self) -> _FakeConn:
        if self.fail_connect:
            raise RuntimeError("simulated connect failure")
        self.connections_opened += 1
        return _FakeConn(self)


@pytest.fixture
def settings() -> SimpleNamespace:
    return SimpleNamespace(job_name="agent-review", host="testhost")


@pytest.fixture
def store() -> _FakeStore:
    return _FakeStore()


def test_record_job_run_inserts_ok_row(settings, store):
    record_job_run(
        settings,
        started_at=STARTED,
        status="ok",
        summary={"dates": ["2026-06-12"], "reports": 1, "sessions": 5},
        cost_usd=0.1234,
        connect=store.connect,
    )
    assert len(store.job_runs) == 1
    row = store.job_runs[0]
    assert row["job_name"] == "agent-review"
    assert row["host"] == "testhost"
    assert row["started_at"] == STARTED
    assert row["status"] == "ok"
    assert row["cost_usd"] == 0.1234
    assert row["summary"]["reports"] == 1


def test_record_job_run_uses_its_own_connection(settings, store):
    before = store.connections_opened
    record_job_run(
        settings, started_at=STARTED, status="ok", summary={}, connect=store.connect
    )
    assert store.connections_opened == before + 1


def test_cost_usd_may_be_null(settings, store):
    # A quiet day persists no report -> cost_usd None keeps the column NULL.
    record_job_run(
        settings, started_at=STARTED, status="ok", summary={"reports": 0},
        cost_usd=None, connect=store.connect,
    )
    assert store.job_runs[0]["cost_usd"] is None


def test_record_job_run_propagates_failures(settings, store):
    store.fail_connect = True
    with pytest.raises(RuntimeError, match="simulated connect failure"):
        record_job_run(
            settings, started_at=STARTED, status="ok", summary={}, connect=store.connect
        )


def test_record_best_effort_swallows_failures(settings, store):
    store.fail_connect = True
    # must not raise — the original run error wins
    record_best_effort(
        settings,
        started_at=STARTED,
        status="error",
        summary={"error": "boom"},
        connect=store.connect,
    )
    assert store.job_runs == []
