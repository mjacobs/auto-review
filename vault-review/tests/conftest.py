"""Shared fakes for the PG run-recording seam (auto-review-2vv).

Mirrors renderer/tests/conftest.py, trimmed to what runlog needs: an in-memory
stand-in for the psycopg connection/cursor shape (`with connect() as conn`,
`conn.cursor()`, `execute`) that dispatches on the module-level SQL constant, so
tests exercise the real record/best-effort logic without a live database.
"""

from __future__ import annotations

import json
from contextlib import contextmanager

import pytest

from vault_review import config, runlog


class FakeCursor:
    def __init__(self, store: FakeStore) -> None:
        self.store = store

    def __enter__(self) -> FakeCursor:
        return self

    def __exit__(self, *exc) -> None:
        return None

    def execute(self, sql: str, params: dict | None = None) -> None:
        params = params or {}
        if sql == runlog.SQL_INSERT_JOB_RUN:
            row = dict(params)
            row["summary"] = json.loads(row["summary"])
            self.store.job_runs.append(row)
        else:  # pragma: no cover - a new query needs a fake branch
            raise AssertionError(f"unexpected SQL in fake store:\n{sql}")


class FakeConn:
    def __init__(self, store: FakeStore) -> None:
        self.store = store

    def cursor(self) -> FakeCursor:
        return FakeCursor(self.store)


class FakeStore:
    """In-memory ops.job_runs + a connect() factory."""

    def __init__(self) -> None:
        self.job_runs: list[dict] = []
        self.connections_opened = 0
        self.fail_connect = False  # make connect itself raise (best-effort tests)

    @contextmanager
    def connect(self):
        if self.fail_connect:
            raise RuntimeError("simulated connect failure")
        self.connections_opened += 1
        yield FakeConn(self)


@pytest.fixture
def settings(monkeypatch: pytest.MonkeyPatch, tmp_path) -> config.Settings:
    """Fresh Settings against a tmp vault; resets the module-level cache."""
    monkeypatch.setenv(
        "VAULT_REVIEW_PG_DSN",
        "postgresql://vault_review_job@db.example:5432/agentsview",
    )
    monkeypatch.setenv("VAULT_PATH", str(tmp_path / "vault"))
    monkeypatch.setenv("TZ", "America/Los_Angeles")
    monkeypatch.setenv("VAULT_REVIEW_HOST", "testhost")
    monkeypatch.setattr(config, "_settings", None)
    return config.get_settings()


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> FakeStore:
    """A fake PG store wired in as vault_review.db.connect."""
    from vault_review import db

    fake = FakeStore()
    monkeypatch.setattr(db, "connect", fake.connect)
    return fake
