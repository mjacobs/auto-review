"""Persist digest rows to the vault_review PG schema (auto-review-hg6.7).

vault-review's real store: each run UPSERTs one self-describing row per window
into ``vault_review.daily_digests`` / ``weekly_digests`` — the ``events`` jsonb
built by `dossier.build_events` (per-file summaries included, because
`summarize_file` reads the working tree at digest time). The check-in renderer
reads these rows and projects the dossier section into the note, so the markdown
becomes a projection rather than the store.

Mirrors `runlog`: a SEPARATE short-lived connection, the DSN is OPTIONAL (a
manual / no-PG run writes its markdown and simply persists nothing), and a
`connect` seam lets tests dispatch on the SQL constants without a live DB.
Keyed UPSERT (digest_date / week_label) makes re-runs idempotent.
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Callable

from . import db
from .config import Settings

SQL_UPSERT_DAILY = """
INSERT INTO vault_review.daily_digests
    (digest_date, window_start, window_end, events, generated_at)
VALUES (%(digest_date)s, %(window_start)s, %(window_end)s, %(events)s::jsonb, now())
ON CONFLICT (digest_date) DO UPDATE SET
    window_start = EXCLUDED.window_start,
    window_end   = EXCLUDED.window_end,
    events       = EXCLUDED.events,
    generated_at = now()
"""

SQL_UPSERT_WEEKLY = """
INSERT INTO vault_review.weekly_digests
    (week_label, window_start, window_end, events, generated_at)
VALUES (%(week_label)s, %(window_start)s, %(window_end)s, %(events)s::jsonb, now())
ON CONFLICT (week_label) DO UPDATE SET
    window_start = EXCLUDED.window_start,
    window_end   = EXCLUDED.window_end,
    events       = EXCLUDED.events,
    generated_at = now()
"""

# connect() seam: any zero-arg callable yielding a psycopg-shaped connection
# context manager (tests pass fakes; production default is db.connect).
ConnectFn = Callable[[], object]


def _localize(ts: dt.datetime, tz: dt.tzinfo) -> dt.datetime:
    """Attach ``tz`` to a naive window bound before it hits a timestamptz column.

    `day_date_range` / `week_date_range` return NAIVE local datetimes (they feed
    git log --since/--until, which wants local wall-clock). Sent naive into a
    timestamptz column, libpq/PG would interpret them in the DB session's zone —
    wrong UTC instants whenever that differs from the vault's zone. Interpreting
    them as the configured local zone here fixes that; an already-aware bound is
    passed through unchanged.
    """
    return ts if ts.tzinfo is not None else ts.replace(tzinfo=tz)


def persist_daily(
    settings: Settings,
    *,
    digest_date: dt.date,
    window_start: dt.datetime,
    window_end: dt.datetime,
    events: list[dict],
    connect: ConnectFn | None = None,
) -> bool:
    """UPSERT the day's digest row. Returns True if a row was written, False
    when PG liveness is not configured (no DSN — same optionality as runlog).

    Raised errors propagate: unlike `record_best_effort`, a failed persist is a
    real failure of the run (the row IS the store), surfaced loudly rather than
    swallowed — the OMG-003 lesson that a silent write hides a broken invariant.
    """
    if settings.pg_dsn is None:
        return False
    connect = connect or db.connect
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            SQL_UPSERT_DAILY,
            {
                "digest_date": digest_date,
                "window_start": _localize(window_start, settings.tz),
                "window_end": _localize(window_end, settings.tz),
                "events": json.dumps(events),
            },
        )
    return True


def persist_weekly(
    settings: Settings,
    *,
    week_label: str,
    window_start: dt.datetime,
    window_end: dt.datetime,
    events: list[dict],
    connect: ConnectFn | None = None,
) -> bool:
    """UPSERT the week's digest row. See `persist_daily` for semantics."""
    if settings.pg_dsn is None:
        return False
    connect = connect or db.connect
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            SQL_UPSERT_WEEKLY,
            {
                "week_label": week_label,
                "window_start": _localize(window_start, settings.tz),
                "window_end": _localize(window_end, settings.tz),
                "events": json.dumps(events),
            },
        )
    return True


__all__ = [
    "SQL_UPSERT_DAILY",
    "SQL_UPSERT_WEEKLY",
    "persist_daily",
    "persist_weekly",
]
