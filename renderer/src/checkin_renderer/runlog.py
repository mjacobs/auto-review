"""ops.job_runs run-recording (DESIGN.md decision 5).

memex-sync's exact pattern (memex-sync/src/memex_sync/sync.py): the main work
happens first, then a SEPARATE connection inserts an 'ok' row with a summary
(`{date, mode, sections: {...}, note_path}`), and a best-effort 'error' row on
exception — the original error still propagates, and a crashed run inserts
nothing and simply goes overdue. job_name must be pre-registered in ops.jobs
(FK; seeded at Phase 2 deploy). Requires the 0006_renderer_runs.sql grant.
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
    started_at: dt.datetime,
    status: str,
    summary: dict,
    connect: ConnectFn | None = None,
) -> None:
    """Append the run to ops.job_runs on its OWN connection/transaction.

    Called after the render has finished (ok) or failed (error), so the run
    row never shares a transaction with anything else — a job_runs failure
    can't undo a written note, and a failed render still records its 'error'
    row (the doctor's liveness evidence).
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


def record_best_effort(settings: Settings, **kwargs) -> None:
    """Record an error run; swallow recording failures (original error wins)."""
    # e.g. the DB itself is down — the original render error must still propagate
    with contextlib.suppress(Exception):
        record_job_run(settings, **kwargs)


__all__ = ["SQL_INSERT_JOB_RUN", "record_job_run", "record_best_effort"]
