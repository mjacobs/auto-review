"""ops.job_runs run-recording for agent-review (auto-review-hg6.8).

agent-review's daily (DB-only) run persists ``agent_review.daily_reports``
but, before hg6.8, wrote no ``ops.job_runs`` row — so the doctor (which moved
from cron.log+marker liveness to querying ``ops.job_runs``) could not see it.

This records ONE row per ``run`` invocation on a SEPARATE connection — the
memex-sync/renderer precedent: the report commits first, then an ``ok`` row
(or a best-effort ``error`` row on exception) lands in its own transaction. A
job_runs failure therefore can't roll back a persisted report, and a crashed
run writes no row at all and simply goes overdue under the doctor's liveness
check. ``job_name`` ('agent-review') is pre-registered in ``ops.jobs`` (FK;
db/migrations/0007); the ``agent_review`` role already holds INSERT on
``ops.job_runs`` (db/migrations/0005 — INSERT only, no SELECT).
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
VALUES (%(job_name)s, %(host)s, %(started_at)s, now(), %(status)s, %(cost_usd)s, %(summary)s::jsonb)
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
    cost_usd: float | None = None,
    connect: ConnectFn | None = None,
) -> None:
    """Append the run to ops.job_runs on its OWN connection/transaction.

    Called after the day(s) finished (ok) or failed (error). ``cost_usd`` is the
    run's summed LLM cost (None/0 on a no-report day) — the one job whose cost
    column is meaningful, since memex-sync/renderer do no LLM work.
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
                "cost_usd": cost_usd,
                "summary": json.dumps(summary),
            },
        )


def record_best_effort(settings: Settings, **kwargs) -> None:
    """Record an error run; swallow recording failures (original error wins)."""
    # e.g. the DB itself is down — the original run error must still propagate.
    with contextlib.suppress(Exception):
        record_job_run(settings, **kwargs)


__all__ = ["SQL_INSERT_JOB_RUN", "record_job_run", "record_best_effort"]
