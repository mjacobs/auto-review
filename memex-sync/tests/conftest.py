"""Shared fakes: a feed of Thoughts + an in-memory stand-in for the PG layer.

The fake store implements just enough of the psycopg connection/cursor shape
for sync.py's seams (`with connect() as conn`, `conn.cursor()`, `execute`,
`fetchone`, `rowcount`) and dispatches on the module-level SQL constants, so
tests exercise the real sync logic — watermark reads, upsert/seed semantics,
transaction rollback on error — without a live database.
"""

from __future__ import annotations

import copy
import json
from contextlib import contextmanager

import pytest

from memex_sync import sync
from memex_sync.client import Thought
from memex_sync.config import Settings


def make_thought(seq: int, *, content: str | None = None, thought_id: str | None = None) -> Thought:
    ts = 1_700_000_000_000 + seq * 60_000
    return Thought(
        id=thought_id or f"{seq:08d}-1111-2222-3333-444444444444",
        seq=seq,
        content=content if content is not None else f"content {seq}",
        source="test",
        summary=None,
        tags=("alpha",) if seq % 2 else (),
        created_at_ms=ts,
        updated_at_ms=ts,
    )


def make_fetch(rows: list[Thought]):
    """A fake client.fetch_since over an in-memory corpus."""

    def fetch(last_seq: int, *, settings: Settings | None = None) -> list[Thought]:
        return sorted((t for t in rows if t.seq > last_seq), key=lambda t: t.seq)

    return fetch


class FakeCursor:
    def __init__(self, store: FakeStore) -> None:
        self.store = store
        self.rowcount = -1
        self._row: dict | None = None

    def __enter__(self) -> FakeCursor:
        return self

    def __exit__(self, *exc) -> None:
        return None

    def fetchone(self) -> dict | None:
        return self._row

    def execute(self, sql: str, params: dict | None = None) -> None:  # noqa: C901
        params = params or {}
        if sql == sync.SQL_SELECT_WATERMARK:
            seq = self.store.sync_state.get(params["consumer"])
            self._row = None if seq is None else {"last_seq": seq}
        elif sql == sync.SQL_UPSERT_CAPTURE:
            self.store.captures[params["id"]] = dict(params)
            self.rowcount = 1
        elif sql == sync.SQL_SEED_TRIAGE:
            if params["capture_id"] in self.store.triage:
                self.rowcount = 0  # ON CONFLICT DO NOTHING
            else:
                self.store.triage[params["capture_id"]] = {"state": "untriaged"}
                self.rowcount = 1
        elif sql == sync.SQL_UPSERT_WATERMARK:
            self.store.sync_state[params["consumer"]] = params["last_seq"]
            self.rowcount = 1
        elif sql == sync.SQL_INSERT_JOB_RUN:
            row = dict(params)
            row["summary"] = json.loads(row["summary"])
            self.store.job_runs.append(row)
            self.rowcount = 1
        elif sql == sync.SQL_COUNT_CAPTURES:
            self._row = {"n": len(self.store.captures)}
        elif sql == sync.SQL_COUNT_UNTRIAGED:
            self._row = {"n": sum(1 for t in self.store.triage.values() if t["state"] == "untriaged")}
        else:  # pragma: no cover - a new query needs a fake branch
            raise AssertionError(f"unexpected SQL in fake store:\n{sql}")


class FakeConn:
    def __init__(self, store: FakeStore) -> None:
        self.store = store

    def cursor(self) -> FakeCursor:
        return FakeCursor(self.store)


class FakeStore:
    """In-memory tables + a connect() factory with commit/rollback semantics."""

    def __init__(self) -> None:
        self.captures: dict[str, dict] = {}
        self.triage: dict[str, dict] = {}
        self.sync_state: dict[str, int] = {}
        self.job_runs: list[dict] = []
        self.connections_opened = 0

    def _snapshot(self) -> dict:
        return copy.deepcopy(
            {
                "captures": self.captures,
                "triage": self.triage,
                "sync_state": self.sync_state,
                "job_runs": self.job_runs,
            }
        )

    def _restore(self, snap: dict) -> None:
        self.captures = snap["captures"]
        self.triage = snap["triage"]
        self.sync_state = snap["sync_state"]
        self.job_runs = snap["job_runs"]

    @contextmanager
    def connect(self):
        """Mimics psycopg's connection context: commit on exit, rollback on error."""
        self.connections_opened += 1
        snap = self._snapshot()
        try:
            yield FakeConn(self)
        except Exception:
            self._restore(snap)  # rollback
            raise


@pytest.fixture
def settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.setenv("PG_DSN", "postgresql://memex_sync@db.example:5432/agentsview")
    monkeypatch.setenv("MEMEX_URL", "https://memex.example/api")
    monkeypatch.setenv("MEMEX_CLIENT_ID", "id")
    monkeypatch.setenv("MEMEX_CLIENT_SECRET", "secret")
    monkeypatch.setenv("MEMEX_SYNC_HOST", "testhost")
    return Settings()


@pytest.fixture
def store() -> FakeStore:
    return FakeStore()
