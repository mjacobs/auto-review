"""ops.job_runs run-recording (auto-review-2vv).

Mirrors the renderer's pattern (renderer/src/checkin_renderer/runlog.py): the
main work (the vault section write) happens first, then a SEPARATE connection
inserts an 'ok' row with a summary (`{date|week_label, events, note_path}`), and
a best-effort 'error' row on exception — the original error still propagates, and
a crashed run inserts nothing and simply goes overdue. job_name must be
pre-registered in ops.jobs (FK; seeded by db/migrations/0008). Requires the
vault_review_job INSERT grant on ops.job_runs (db/migrations/0005).

vault-review does no LLM work, so cost_usd is always NULL.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import json
from collections.abc import Callable

from . import db
from .config import Settings

SQL_INSERT_JOB_RUN = """
INSERT INTO ops.job_runs (job_name, host, started_at, finished_at, status, cost_usd, summary)
VALUES (%(job_name)s, %(host)s, %(started_at)s, now(), %(status)s, NULL, %(summary)s::jsonb)
"""

# connect() seam: any zero-arg callable yielding a psycopg-shaped connection
# context manager (tests pass fakes; production default is db.connect).
ConnectFn = Callable[[], object]


def record_job_run(
    settings: Settings,
    *,
    job_name: str,
    started_at: dt.datetime,
    status: str,
    summary: dict,
    connect: ConnectFn | None = None,
) -> None:
    """Append the run to ops.job_runs on its OWN connection/transaction.

    Called after the section has been written (ok) or failed (error), so the run
    row never shares a transaction with the vault write — a job_runs failure
    can't undo a written section, and a failed run still records its 'error' row
    (the doctor's liveness evidence). ``job_name`` is passed explicitly because
    one CLI process serves both the daily and weekly jobs.

    PG liveness is OPTIONAL (config.py): with no DSN the run still writes its
    section and simply records no row. Without this early return the success
    path would hit db.connect()'s RuntimeError *after* the vault write, crashing
    an otherwise-successful manual / no-PG run (the error path is already
    guarded by record_best_effort; only the ok path was exposed).
    """
    if settings.pg_dsn is None:
        return
    connect = connect or db.connect
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            SQL_INSERT_JOB_RUN,
            {
                "job_name": job_name,
                "host": settings.host,
                "started_at": started_at,
                "status": status,
                "summary": json.dumps(summary),
            },
        )


def record_best_effort(settings: Settings, **kwargs) -> None:
    """Record an error run; swallow recording failures (original error wins)."""
    # e.g. the DB itself is down — the original section-write error must still propagate
    with contextlib.suppress(Exception):
        record_job_run(settings, **kwargs)


__all__ = ["SQL_INSERT_JOB_RUN", "record_job_run", "record_best_effort"]
