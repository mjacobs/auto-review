"""All SQL the renderer runs, plus typed row dataclasses per section.

The renderer fetches nothing from the outside world — every query here reads
a per-domain PG schema (DESIGN.md, "projection, not pipeline"). SQL lives in
module-level constants so test fakes can dispatch on them (memex-sync
precedent).
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any

# ── SQL ───────────────────────────────────────────────────────────────────────

# memex inbox section: a local-day capture window, same semantics as
# memex-review's collect_for_date (created_at ∈ [D 00:00, D+1 00:00) local).
SQL_MEMEX_CAPTURES = """
SELECT id, content, summary, tags, created_at
  FROM memex.captures
 WHERE created_at >= %(start)s
   AND created_at < %(end)s
 ORDER BY created_at
"""

# agent-review section: the producer's one row per day.
SQL_AGENT_REPORT = """
SELECT report_date, generated_at, narrative_md, stats
  FROM agent_review.daily_reports
 WHERE report_date = %(date)s
"""

# ── row shapes ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class CaptureRow:
    """One memex.captures row inside the rendered day window."""

    id: str
    content: str
    summary: str | None
    tags: tuple[str, ...]
    created_at: dt.datetime  # timestamptz


@dataclass(frozen=True)
class AgentReportRow:
    """One agent_review.daily_reports row."""

    report_date: dt.date
    generated_at: dt.datetime
    narrative_md: str
    stats: dict[str, Any]


# ── fetchers ──────────────────────────────────────────────────────────────────


def fetch_memex_captures(conn, start: dt.datetime, end: dt.datetime) -> list[CaptureRow]:
    """Captures with `start <= created_at < end`, oldest first."""
    with conn.cursor() as cur:
        cur.execute(SQL_MEMEX_CAPTURES, {"start": start, "end": end})
        rows = cur.fetchall()
    return [
        CaptureRow(
            id=r["id"],
            content=r["content"],
            summary=r["summary"],
            tags=tuple(r["tags"] or ()),
            created_at=r["created_at"],
        )
        for r in rows
    ]


def fetch_agent_report(conn, date: dt.date) -> AgentReportRow | None:
    """The day's daily_reports row, or None when the producer hasn't landed one."""
    with conn.cursor() as cur:
        cur.execute(SQL_AGENT_REPORT, {"date": date})
        row = cur.fetchone()
    if row is None:
        return None
    return AgentReportRow(
        report_date=row["report_date"],
        generated_at=row["generated_at"],
        narrative_md=row["narrative_md"],
        stats=dict(row["stats"]),
    )
