"""Shared fakes: an in-memory stand-in for the PG layer + settings plumbing.

The fake store implements just enough of the psycopg connection/cursor shape
for the renderer's seams (`with connect() as conn`, `conn.cursor()`,
`execute`, `fetchone`/`fetchall`) and dispatches on the module-level SQL
constants (memex-sync's test pattern), so tests exercise the real query/
render/record logic without a live database. The golden fixtures under
tests/fixtures/ are synthetic (public repo; see test_golden_2026_06_10 docstring).
"""

from __future__ import annotations

import datetime as dt
import json
from contextlib import contextmanager
from typing import Any

import pytest

from checkin_renderer import config, queries, runlog

# ── row builders ──────────────────────────────────────────────────────────────

PT = dt.timezone(dt.timedelta(hours=-7))  # America/Los_Angeles in June (PDT)


def make_capture_row(
    hhmm: str = "08:30",
    *,
    date: dt.date = dt.date(2026, 6, 10),
    content: str = "a capture",
    summary: str | None = None,
    tags: tuple[str, ...] = (),
    capture_id: str = "cap-1",
) -> dict[str, Any]:
    """A memex.captures row dict as the fake store holds it."""
    h, m = (int(x) for x in hhmm.split(":"))
    return {
        "id": capture_id,
        "content": content,
        "summary": summary,
        "tags": list(tags),
        "created_at": dt.datetime.combine(date, dt.time(h, m), tzinfo=PT),
    }


def make_agent_row(
    *,
    date: dt.date = dt.date(2026, 6, 10),
    narrative_md: str = "Did some things.",
    stats: dict | None = None,
) -> dict[str, Any]:
    """An agent_review.daily_reports row dict as the fake store holds it."""
    return {
        "report_date": date,
        "generated_at": dt.datetime.combine(date, dt.time(0, 23), tzinfo=PT),
        "narrative_md": narrative_md,
        "stats": stats or {"sessions": 2, "agents": {"claude": 2}, "projects": {"p": 2}},
    }


# ── fake PG layer ─────────────────────────────────────────────────────────────


class FakeCursor:
    def __init__(self, store: FakeStore) -> None:
        self.store = store
        self._rows: list[dict] = []

    def __enter__(self) -> FakeCursor:
        return self

    def __exit__(self, *exc) -> None:
        return None

    def execute(self, sql: str, params: dict | None = None) -> None:
        params = params or {}
        if sql == queries.SQL_MEMEX_CAPTURES:
            self.store.maybe_fail()
            self._rows = sorted(
                (
                    r
                    for r in self.store.captures
                    if params["start"] <= r["created_at"] < params["end"]
                ),
                key=lambda r: r["created_at"],
            )
        elif sql == queries.SQL_AGENT_REPORT:
            self.store.maybe_fail()
            row = self.store.agent_reports.get(params["date"])
            self._rows = [row] if row is not None else []
        elif sql == runlog.SQL_INSERT_JOB_RUN:
            row = dict(params)
            row["summary"] = json.loads(row["summary"])
            self.store.job_runs.append(row)
        else:  # pragma: no cover - a new query needs a fake branch
            raise AssertionError(f"unexpected SQL in fake store:\n{sql}")

    def fetchone(self) -> dict | None:
        return self._rows[0] if self._rows else None

    def fetchall(self) -> list[dict]:
        return list(self._rows)


class FakeConn:
    def __init__(self, store: FakeStore) -> None:
        self.store = store

    def cursor(self) -> FakeCursor:
        return FakeCursor(self.store)


class FakeStore:
    """In-memory tables + a connect() factory."""

    def __init__(self) -> None:
        self.captures: list[dict] = []
        self.agent_reports: dict[dt.date, dict] = {}
        self.job_runs: list[dict] = []
        self.connections_opened = 0
        self.fail_queries = False  # make section queries raise (error-path tests)
        self.fail_connect = False  # make connect itself raise (best-effort tests)

    def maybe_fail(self) -> None:
        if self.fail_queries:
            raise RuntimeError("boom: simulated query failure")

    @contextmanager
    def connect(self):
        if self.fail_connect:
            raise RuntimeError("boom: simulated connect failure")
        self.connections_opened += 1
        yield FakeConn(self)


# ── fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def settings(monkeypatch: pytest.MonkeyPatch, tmp_path) -> config.Settings:
    """Fresh Settings against a tmp vault; resets the module-level cache."""
    monkeypatch.setenv(
        "CHECKIN_RENDERER_PG_DSN",
        "postgresql://checkin_renderer@db.example:5432/agentsview",
    )
    monkeypatch.setenv("VAULT_PATH", str(tmp_path / "vault"))
    monkeypatch.setenv("TZ", "America/Los_Angeles")
    monkeypatch.setenv("RENDER_MODE", "bracket")
    monkeypatch.setenv("CHECKIN_RENDERER_HOST", "testhost")
    monkeypatch.setattr(config, "_settings", None)
    return config.get_settings()


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> FakeStore:
    """A fake PG store wired in as checkin_renderer.db.connect."""
    from checkin_renderer import db

    fake = FakeStore()
    monkeypatch.setattr(db, "connect", fake.connect)
    return fake
