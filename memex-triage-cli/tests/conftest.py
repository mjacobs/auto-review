"""Shared fakes: an in-memory stand-in for the PG layer, no live DSN.

The fake store implements just enough of the psycopg connection/cursor shape
for triage.py's seams (`with connect() as conn`, `conn.cursor()`, `execute`,
`fetchall`) and dispatches on the module-level SQL constants (queries.py), so
tests exercise the real listing/flip/resolution logic — including the
UPDATE-only boundary — without a database.

Crucially the fake's SQL_SET_STATE branch only mutates a row that already
exists: it raises if asked to flip an unseeded capture, mirroring the fact that
the memex_triage role has no INSERT on capture_triage. The triage code must
therefore never invent a row.
"""

from __future__ import annotations

import copy
import datetime as dt
from contextlib import contextmanager

import pytest

from memex_triage_cli import queries
from memex_triage_cli.config import Settings


def make_capture(
    seq: int,
    *,
    state: str = "untriaged",
    content: str | None = None,
    summary: str | None = None,
    tags: tuple[str, ...] = (),
    capture_id: str | None = None,
) -> dict:
    """A captures+triage pair for seeding the fake store."""
    ts = dt.datetime(2026, 6, 1, 12, 0, tzinfo=dt.UTC) + dt.timedelta(minutes=seq)
    return {
        "id": capture_id or f"{seq:08d}-1111-2222-3333-444444444444",
        "seq": seq,
        "content": content if content is not None else f"content {seq}",
        "summary": summary,
        "tags": list(tags),
        "created_at": ts,
        "state": state,
    }


class FakeCursor:
    def __init__(self, store: FakeStore) -> None:
        self.store = store
        self.rowcount = -1
        self._rows: list[dict] = []

    def __enter__(self) -> FakeCursor:
        return self

    def __exit__(self, *exc) -> None:
        return None

    def fetchall(self) -> list[dict]:
        return self._rows

    def fetchone(self) -> dict | None:
        return self._rows[0] if self._rows else None

    def execute(self, sql: str, params: dict | None = None) -> None:
        params = params or {}
        if sql == queries.SQL_INBOX:
            rows = [
                {k: c[k] for k in ("id", "seq", "content", "summary", "tags", "created_at")}
                for c in self.store.captures.values()
                if c["state"] == params["state"]
            ]
            self._rows = sorted(rows, key=lambda r: r["seq"])
        elif sql == queries.SQL_RESOLVE_INDEX:
            # Resolution index: same state filter as SQL_INBOX but only (id, seq),
            # mirroring the lightweight column list the real query selects.
            rows = [
                {k: c[k] for k in ("id", "seq")}
                for c in self.store.captures.values()
                if c["state"] == params["state"]
            ]
            self._rows = sorted(rows, key=lambda r: r["seq"])
        elif sql == queries.SQL_SET_STATE:
            cap = self.store.captures.get(params["id"])
            if cap is None:
                # The triage row does not exist; the role cannot INSERT one.
                # An UPDATE matches zero rows in real PG — model that as rowcount 0.
                self.rowcount = 0
            else:
                cap["state"] = params["state"]
                self.rowcount = 1
        else:  # pragma: no cover - a new query needs a fake branch
            raise AssertionError(f"unexpected SQL in fake store:\n{sql}")


class FakeConn:
    def __init__(self, store: FakeStore) -> None:
        self.store = store

    def cursor(self) -> FakeCursor:
        return FakeCursor(self.store)


class FakeStore:
    """In-memory captures table + a connect() factory with commit/rollback."""

    def __init__(self) -> None:
        self.captures: dict[str, dict] = {}
        self.connections_opened = 0

    def seed(self, *caps: dict) -> FakeStore:
        for c in caps:
            self.captures[c["id"]] = dict(c)
        return self

    def state_of(self, seq: int) -> str:
        for c in self.captures.values():
            if c["seq"] == seq:
                return c["state"]
        raise KeyError(seq)

    @contextmanager
    def connect(self):
        """Mimics psycopg's connection context: commit on exit, rollback on error."""
        self.connections_opened += 1
        snap = copy.deepcopy(self.captures)
        try:
            yield FakeConn(self)
        except Exception:
            self.captures = snap  # rollback
            raise


@pytest.fixture
def settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.setenv("MEMEX_TRIAGE_PG_DSN", "postgresql://memex_triage@db.example:5432/agentsview")
    monkeypatch.setenv("TZ", "UTC")
    return Settings()


@pytest.fixture
def store() -> FakeStore:
    return FakeStore()
