"""agent-review section: agent_review.daily_reports row -> markdown.

Two paths (DESIGN.md decision 3):

* legacy-normalize — until hg6.6, synth.persist_report stores the FULL
  rendered section (heading `## agent-review — …` + trailing
  `<!-- agent-review:report_date=… -->` marker) in narrative_md. When the
  stored text starts with that heading, reuse it verbatim minus the trailing
  marker line — the renderer bracket replaces per-section markers. This
  branch is deleted in step B's cleanup.
* canonical — post-hg6.6 rows hold a clean narrative; render the canonical
  heading + summary line + narrative + stats table from the stats jsonb.

Pure function: no I/O.
"""

from __future__ import annotations

import datetime as dt
import re
from typing import Any

from ..queries import AgentReportRow

_LEGACY_HEADING_PREFIX = "## agent-review"

# The trailing marker comment the legacy rows carry (see
# agent-review/src/agent_review/synth.py, _render_section / section_marker).
_LEGACY_MARKER_RE = re.compile(r"\n?<!-- agent-review:report_date=[^>]*-->\s*$")


def is_legacy_row(narrative_md: str) -> bool:
    """True when the stored narrative is a full pre-hg6.6 rendered section."""
    return narrative_md.lstrip().startswith(_LEGACY_HEADING_PREFIX)


def render_agent_section(report: AgentReportRow | None, date: dt.date) -> str:
    """Render the agent-review section body (no trailing newline)."""
    if report is None:
        return (
            f"## agent-review — {date.isoformat()}\n\n"
            f"_no agent-review report row for {date.isoformat()}_"
        )
    if is_legacy_row(report.narrative_md):
        return _normalize_legacy(report.narrative_md)
    return _render_canonical(report, date)


def _normalize_legacy(narrative_md: str) -> str:
    """Strip the stored section's trailing marker; reuse the body verbatim."""
    return _LEGACY_MARKER_RE.sub("", narrative_md).rstrip()


def _render_canonical(report: AgentReportRow, date: dt.date) -> str:
    """Canonical render for clean (post-hg6.6) narrative rows.

    Heading + summary line + narrative + stats table, all derivable from the
    row — no producer-run-time values like the legacy window end. The exact
    canonical shape is finalized with hg6.6's storage cleanup.
    """
    stats = report.stats
    agents_str = ", ".join(f"{a}×{n}" for a, n in stats.get("agents", {}).items()) or "—"
    cost = float(stats.get("est_total_cost_usd", 0.0))
    summary_line = (
        f"_{stats.get('sessions', 0)} sessions · "
        f"{len(stats.get('projects', {}))} projects · ~${cost:.2f} · {agents_str}_"
    )
    return (
        f"## agent-review — {date.isoformat()}\n\n"
        f"{summary_line}\n\n"
        f"{report.narrative_md.strip()}\n\n"
        f"### stats\n\n{_stats_table(stats)}"
    )


def _stats_table(stats: dict[str, Any]) -> str:
    """The same stats table the producer renders today (synth._render_section)."""
    agents_str = ", ".join(f"{a}×{n}" for a, n in stats.get("agents", {}).items()) or "—"
    cost = float(stats.get("est_total_cost_usd", 0.0))
    return (
        "| sessions | agents | msgs | session out tok | peak ctx | artifacts | blockers | est. cost |\n"
        "|---------:|:-------|-----:|---------------:|--------:|---------:|--------:|---------:|\n"
        f"| {stats.get('sessions', 0)} | {agents_str} | {stats.get('messages', 0)} | "
        f"{stats.get('session_output_tokens_sum', 0)} | {stats.get('peak_context_tokens_max', 0)} | "
        f"{stats.get('artifact_count', 0)} | {stats.get('blocker_count', 0)} | ${cost:.4f} |"
    )


__all__ = ["is_legacy_row", "render_agent_section"]
