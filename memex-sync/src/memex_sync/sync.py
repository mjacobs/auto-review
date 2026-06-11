"""Core sync: feed -> memex.captures upsert, triage seed, watermark, job_runs.

Transaction shape (the load-bearing part):

* One MAIN connection per run. The watermark read, every capture upsert, every
  triage seed, and the watermark advance all happen on it; psycopg's connection
  context commits the lot on clean exit and rolls back everything on exception.
  So a crash mid-batch leaves the watermark untouched and the next run
  re-fetches the same rows — upserts make the replay idempotent.
* One SEPARATE connection for the ops.job_runs row, opened after the main one
  has committed or rolled back. A failed sync therefore still records its
  'error' run row (the doctor's liveness evidence), and a job_runs failure
  can't roll back delivered captures.

What sync writes — and deliberately does not:

* memex.captures: INSERT ... ON CONFLICT (id) DO UPDATE. The feed may
  re-deliver rows after a watermark reset; capture id is the dedupe key.
* memex.capture_triage: seeded 'untriaged' via ON CONFLICT DO NOTHING. Sync
  NEVER updates existing triage state — that is triage-surface-owned, and the
  memex_sync role's grants (INSERT but no UPDATE on capture_triage,
  db/migrations/0005_roles.sql) enforce it.
* memex.sync_state: one row per consumer. Advanced only when there is
  something to record (a non-empty batch, or an explicit --since).
"""

from __future__ import annotations

import contextlib
import datetime as dt
import json
import traceback
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from . import client as client_mod
from . import db
from .client import Thought
from .config import Settings

# ── SQL (module-level constants so tests can dispatch on them) ────────────────

SQL_SELECT_WATERMARK = """
SELECT last_seq FROM memex.sync_state WHERE consumer = %(consumer)s
"""

SQL_UPSERT_CAPTURE = """
INSERT INTO memex.captures
    (id, seq, content, summary, tags, source, created_at, updated_at, synced_at)
VALUES
    (%(id)s, %(seq)s, %(content)s, %(summary)s, %(tags)s, %(source)s,
     %(created_at)s, %(updated_at)s, now())
ON CONFLICT (id) DO UPDATE SET
    seq        = EXCLUDED.seq,
    content    = EXCLUDED.content,
    summary    = EXCLUDED.summary,
    tags       = EXCLUDED.tags,
    source     = EXCLUDED.source,
    created_at = EXCLUDED.created_at,
    updated_at = EXCLUDED.updated_at,
    synced_at  = now()
"""

SQL_SEED_TRIAGE = """
INSERT INTO memex.capture_triage (capture_id)
VALUES (%(capture_id)s)
ON CONFLICT (capture_id) DO NOTHING
"""

SQL_UPSERT_WATERMARK = """
INSERT INTO memex.sync_state (consumer, last_seq, updated_at)
VALUES (%(consumer)s, %(last_seq)s, now())
ON CONFLICT (consumer) DO UPDATE SET
    last_seq   = EXCLUDED.last_seq,
    updated_at = now()
"""

SQL_INSERT_JOB_RUN = """
INSERT INTO ops.job_runs (job_name, host, started_at, finished_at, status, cost_usd, summary)
VALUES (%(job_name)s, %(host)s, %(started_at)s, now(), %(status)s, NULL, %(summary)s::jsonb)
"""

SQL_COUNT_CAPTURES = """
SELECT count(*) AS n FROM memex.captures
"""

SQL_COUNT_UNTRIAGED = """
SELECT count(*) AS n FROM memex.capture_triage WHERE state = 'untriaged'
"""

# connect() seam: any zero-arg callable yielding a psycopg-shaped connection
# context manager (tests pass fakes; production default is db.connect).
ConnectFn = Callable[[], object]
FetchFn = Callable[..., list[Thought]]


@dataclass(frozen=True)
class SyncResult:
    consumer: str
    since: int  # the seq the feed was walked from
    fetched: int
    upserted: int
    triage_seeded: int
    watermark_before: int | None  # None = no sync_state row yet (bootstrap)
    watermark_after: int | None
    dry_run: bool
    thoughts: tuple[Thought, ...] = ()  # the fetched batch (for --print; not in summary)

    @property
    def bootstrapped(self) -> bool:
        return self.watermark_before is None

    def summary(self) -> dict:
        """The ops.job_runs summary payload (and the CLI's report line source)."""
        return {
            "consumer": self.consumer,
            "since": self.since,
            "fetched": self.fetched,
            "upserted": self.upserted,
            "triage_seeded": self.triage_seeded,
            "watermark_before": self.watermark_before,
            "watermark_after": self.watermark_after,
            "bootstrapped": self.bootstrapped,
        }


# ── building blocks ───────────────────────────────────────────────────────────


def load_watermark(conn, consumer: str) -> int | None:
    """The consumer's last delivered seq, or None when no row exists yet."""
    with conn.cursor() as cur:
        cur.execute(SQL_SELECT_WATERMARK, {"consumer": consumer})
        row = cur.fetchone()
    return int(row["last_seq"]) if row else None


def apply_batch(conn, thoughts: Sequence[Thought]) -> tuple[int, int]:
    """Upsert captures + seed triage rows on `conn`. Returns (upserted, seeded).

    `seeded` counts triage rows actually inserted (rowcount of the
    ON CONFLICT DO NOTHING), so re-delivered captures whose triage state has
    already moved on report 0 here — evidence the existing state was preserved.
    """
    upserted = 0
    seeded = 0
    with conn.cursor() as cur:
        for t in thoughts:
            cur.execute(
                SQL_UPSERT_CAPTURE,
                {
                    "id": t.id,
                    "seq": t.seq,
                    "content": t.content,
                    "summary": t.summary,
                    "tags": list(t.tags),
                    "source": t.source,
                    "created_at": t.created_at,
                    "updated_at": t.updated_at,
                },
            )
            upserted += 1
            cur.execute(SQL_SEED_TRIAGE, {"capture_id": t.id})
            seeded += max(cur.rowcount, 0)
    return upserted, seeded


def set_watermark(conn, consumer: str, last_seq: int) -> None:
    with conn.cursor() as cur:
        cur.execute(SQL_UPSERT_WATERMARK, {"consumer": consumer, "last_seq": last_seq})


def record_job_run(
    settings: Settings,
    *,
    started_at: dt.datetime,
    status: str,
    summary: dict,
    connect: ConnectFn | None = None,
) -> None:
    """Append the run to ops.job_runs on its OWN connection/transaction.

    Called after the main connection has committed (ok) or rolled back (error),
    so the run row survives a failed sync. job_name must be pre-registered in
    ops.jobs (FK; the memex_sync role cannot insert registry rows — see
    deploy/README.md).
    """
    connect = connect or db.connect
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            SQL_INSERT_JOB_RUN,
            {
                "job_name": settings.job_name,
                "host": settings.host,
                "started_at": started_at,
                "status": status,
                "summary": json.dumps(summary),
            },
        )


# ── orchestration ─────────────────────────────────────────────────────────────


def run_sync(
    settings: Settings,
    *,
    since: int | None = None,
    dry_run: bool = False,
    connect: ConnectFn | None = None,
    fetch: FetchFn | None = None,
) -> SyncResult:
    """One sync run. Returns the result; raises on failure (after recording it).

    Watermark semantics:
    * normal run: walk the feed from the stored watermark; advance it to the
      batch max within the same transaction as the row writes.
    * bootstrap (no sync_state row): start from seq 0 — the canonical store
      wants the full history, unlike the triage inbox's start-at-head.
    * --since N: walk from N regardless of the stored watermark (re-delivery /
      backfill-from-a-point). The watermark is then advanced to
      max(N, batch max) even on an empty batch, so `--since <head>` is the
      explicit "bootstrap at head, skip history" escape hatch.
    * idle run (nothing new, no --since): no row writes at all — but still a
      job_runs row (the doctor needs liveness evidence).

    dry_run: read-only — no captures, no watermark, no job_runs row.
    """
    connect = connect or db.connect
    fetch = fetch or client_mod.fetch_since
    started_at = dt.datetime.now(tz=dt.UTC)

    try:
        result = _sync_once(settings, since=since, dry_run=dry_run, connect=connect, fetch=fetch)
    except Exception as exc:
        if not dry_run:
            _record_best_effort(
                settings,
                started_at=started_at,
                status="error",
                summary={
                    "consumer": settings.consumer,
                    "error": f"{type(exc).__name__}: {exc}",
                    "trace": traceback.format_exc(limit=5),
                },
                connect=connect,
            )
        raise

    if not dry_run:
        record_job_run(
            settings,
            started_at=started_at,
            status="ok",
            summary=result.summary(),
            connect=connect,
        )
    return result


def _sync_once(
    settings: Settings,
    *,
    since: int | None,
    dry_run: bool,
    connect: ConnectFn,
    fetch: FetchFn,
) -> SyncResult:
    """The main-connection part: read watermark, fetch, write, advance — one txn."""
    with connect() as conn:
        watermark = load_watermark(conn, settings.consumer)
        effective_since = since if since is not None else (watermark or 0)

        thoughts = fetch(effective_since, settings=settings)
        batch_max = max((t.seq for t in thoughts), default=None)

        if since is not None:
            new_watermark = max(since, batch_max or 0, watermark or 0)
        elif batch_max is not None:
            new_watermark = max(batch_max, watermark or 0)
        else:
            new_watermark = None  # idle: leave sync_state untouched

        if dry_run:
            return SyncResult(
                consumer=settings.consumer,
                since=effective_since,
                fetched=len(thoughts),
                upserted=0,
                triage_seeded=0,
                watermark_before=watermark,
                watermark_after=watermark,
                dry_run=True,
                thoughts=tuple(thoughts),
            )

        upserted, seeded = apply_batch(conn, thoughts)
        if new_watermark is not None:
            set_watermark(conn, settings.consumer, new_watermark)
        # the connection context commits everything above atomically on exit

    return SyncResult(
        consumer=settings.consumer,
        since=effective_since,
        fetched=len(thoughts),
        upserted=upserted,
        triage_seeded=seeded,
        watermark_before=watermark,
        watermark_after=new_watermark if new_watermark is not None else watermark,
        dry_run=False,
        thoughts=tuple(thoughts),
    )


def _record_best_effort(settings: Settings, **kwargs) -> None:
    """Record an error run; swallow recording failures (original error wins)."""
    # e.g. the DB itself is down — the original sync error must still propagate
    with contextlib.suppress(Exception):
        record_job_run(settings, **kwargs)


# ── status ────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class StatusSnapshot:
    consumer: str
    watermark: int | None
    server_head: int
    captures: int
    untriaged: int


def status_snapshot(
    settings: Settings,
    *,
    connect: ConnectFn | None = None,
    head_fn: Callable[..., int] | None = None,
) -> StatusSnapshot:
    """Watermark vs server head + mirror row counts, for the `status` verb."""
    connect = connect or db.connect
    head_fn = head_fn or client_mod.server_head
    with connect() as conn:
        watermark = load_watermark(conn, settings.consumer)
        with conn.cursor() as cur:
            cur.execute(SQL_COUNT_CAPTURES)
            captures = int(cur.fetchone()["n"])
            cur.execute(SQL_COUNT_UNTRIAGED)
            untriaged = int(cur.fetchone()["n"])
    return StatusSnapshot(
        consumer=settings.consumer,
        watermark=watermark,
        server_head=head_fn(settings=settings),
        captures=captures,
        untriaged=untriaged,
    )
