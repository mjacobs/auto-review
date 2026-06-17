"""Stage 3: daily synthesis. Read per-session digests + extracted artifacts +
day stats, call Sonnet for the narrative, render the full vault section
(narrative + stats + by-project + artifacts), persist to agent_review.daily_reports."""

from __future__ import annotations

import datetime as dt
from collections import Counter
from importlib.resources import files
from typing import Any

from psycopg.types.json import Json
from tenacity import retry, stop_after_attempt, wait_exponential

from . import llm
from .config import get_settings
from .db import connect
from .digest import Digest, estimate_cost, fetch_pricing
from .extract import SessionBundle

# ─── public entry point ───────────────────────────────────────────────────────


def synthesize_day(
    date: dt.date,
    bundles_with_digests: list[tuple[SessionBundle, Digest]],
    *,
    digest_usages: list[dict[str, int]] | None = None,  # accepted for back-compat
    window_end: dt.datetime | None = None,
) -> DailyReport:
    """Synthesize a daily report. Returns a DailyReport with the rendered
    section markdown ready for the vault writer. Caller is responsible for
    deciding whether to write to vault and/or persist to DB."""
    # Pull cumulative digest token usage from persisted rows so cost reflects
    # the full report, not just this run's incremental spend. Dry-run callers
    # pass explicit usage so fresh non-persisted digests are counted instead.
    session_ids = [b.session_id for b, _ in bundles_with_digests]
    digest_usage_source = (
        digest_usages
        if digest_usages is not None
        else _load_persisted_digest_usages(session_ids)
    )
    stats = _compute_stats(date, bundles_with_digests, digest_usage_source)
    narrative_md, synth_usage = _call_llm(date, bundles_with_digests, stats)

    s = get_settings()
    pricing = fetch_pricing()
    synth_cost = estimate_cost(s.model_synth, synth_usage, pricing)
    total_cost = synth_cost + stats["est_digest_cost_usd"]
    stats["est_synth_cost_usd"] = round(synth_cost, 4)
    stats["est_total_cost_usd"] = round(total_cost, 4)

    section_md = _render_section(date, narrative_md, stats, window_end)

    return DailyReport(
        report_date=date,
        narrative_md=narrative_md,
        section_md=section_md,
        stats=stats,
        sessions_included=[b.session_id for b, _ in bundles_with_digests],
        synth_usage=synth_usage,
        est_cost_usd=round(total_cost, 4),
    )


def persist_report(report: DailyReport) -> None:
    s = get_settings()
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO agent_review.daily_reports
                (report_date, generated_at, model, sessions_included,
                 narrative_md, stats, prompt_tokens, output_tokens,
                 cached_tokens, est_cost_usd)
            VALUES (%s, now(), %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (report_date) DO UPDATE SET
                generated_at      = now(),
                model             = EXCLUDED.model,
                sessions_included = EXCLUDED.sessions_included,
                narrative_md      = EXCLUDED.narrative_md,
                stats             = EXCLUDED.stats,
                prompt_tokens     = EXCLUDED.prompt_tokens,
                output_tokens     = EXCLUDED.output_tokens,
                cached_tokens     = EXCLUDED.cached_tokens,
                est_cost_usd      = EXCLUDED.est_cost_usd
            """,
            (
                report.report_date,
                s.model_synth,
                report.sessions_included,
                report.section_md,
                Json(report.stats),
                report.synth_usage.get("input_tokens", 0),
                report.synth_usage.get("output_tokens", 0),
                report.synth_usage.get("cache_read_input_tokens", 0),
                report.est_cost_usd,
            ),
        )
        conn.commit()


# ─── data shape ──────────────────────────────────────────────────────────────


class DailyReport:
    def __init__(
        self,
        report_date: dt.date,
        narrative_md: str,
        section_md: str,
        stats: dict[str, Any],
        sessions_included: list[str],
        synth_usage: dict[str, int],
        est_cost_usd: float,
    ):
        self.report_date = report_date
        self.narrative_md = narrative_md
        self.section_md = section_md
        self.stats = stats
        self.sessions_included = sessions_included
        self.synth_usage = synth_usage
        self.est_cost_usd = est_cost_usd


def _load_persisted_digest_usages(session_ids: list[str]) -> list[dict[str, int]]:
    """Read prompt/output/cached tokens from the digest cache for the given
    sessions. Used so cost rollups reflect the report's true cost across
    cache-hit re-runs."""
    if not session_ids:
        return []
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT prompt_tokens, output_tokens, cached_tokens "
            "  FROM agent_review.session_digests "
            " WHERE session_id = ANY(%s)",
            (session_ids,),
        )
        rows = cur.fetchall()
    return [
        {
            "input_tokens": r["prompt_tokens"],
            "output_tokens": r["output_tokens"],
            "cache_read_input_tokens": r["cached_tokens"],
        }
        for r in rows
    ]


# ─── stats ───────────────────────────────────────────────────────────────────


def _compute_stats(
    date: dt.date,
    pairs: list[tuple[SessionBundle, Digest]],
    digest_usages: list[dict[str, int]],
) -> dict[str, Any]:
    by_agent: Counter[str] = Counter()
    by_project: Counter[str] = Counter()
    total_msgs = 0
    total_output_tokens = 0
    peak_context = 0
    artifact_count = 0
    blockers: list[str] = []

    for b, d in pairs:
        by_agent[b.agent] += 1
        by_project[d.project or b.project] += 1
        total_msgs += b.message_count
        total_output_tokens += b.total_output_tokens
        peak_context = max(peak_context, b.peak_context_tokens)
        artifact_count += len(d.artifacts)
        blockers.extend(d.blockers)

    s = get_settings()
    pricing = fetch_pricing()
    digest_cost = sum(
        estimate_cost(s.model_digest, u, pricing) for u in digest_usages
    )

    return {
        "date": date.isoformat(),
        "sessions": len(pairs),
        "messages": total_msgs,
        "agents": dict(by_agent.most_common()),
        "projects": dict(by_project.most_common()),
        "session_output_tokens_sum": total_output_tokens,
        "peak_context_tokens_max": peak_context,
        "artifact_count": artifact_count,
        "blocker_count": len(blockers),
        "est_digest_cost_usd": round(digest_cost, 4),
    }


# ─── LLM call ────────────────────────────────────────────────────────────────


def _load_system_prompt() -> str:
    return files("agent_review.prompts").joinpath("synth_system.md").read_text()


@retry(stop=stop_after_attempt(4), wait=wait_exponential(multiplier=2, min=2, max=30))
def _call_llm(
    date: dt.date,
    pairs: list[tuple[SessionBundle, Digest]],
    stats: dict[str, Any],
) -> tuple[str, dict[str, int]]:
    s = get_settings()
    result = llm.complete(
        model=s.model_synth,
        system_prompt=_load_system_prompt(),
        user_content=_render_synth_payload(date, pairs, stats),
        max_tokens=4096,
        settings=s,
    )
    if not result.text:
        raise RuntimeError(
            f"No text in synthesis response (model={s.model_synth}, backend={s.llm_backend})"
        )
    return result.text, result.usage


def _render_synth_payload(
    date: dt.date,
    pairs: list[tuple[SessionBundle, Digest]],
    stats: dict[str, Any],
) -> str:
    parts: list[str] = []
    parts.append(f"# date: {date.isoformat()} (America/Los_Angeles)")
    parts.append(f"# stats\n{_yamlish(stats)}")
    parts.append("\n# session digests\n")
    for b, d in pairs:
        parts.append(_render_pair(b, d))
        parts.append("")
    return "\n".join(parts)


def _render_pair(b: SessionBundle, d: Digest) -> str:
    lines = [
        f"## session {b.session_id}",
        f"- agent: {b.agent}",
        f"- project: {d.project} (extracted: {b.project})",
        f"- started: {b.started_at.isoformat()}  duration: {b.duration_minutes}m",
        f"- outcome: {d.outcome}  confidence: {d.confidence}",
        f"- tags: {', '.join(d.tags) or '(none)'}",
        f"- summary: {d.summary}",
    ]
    if d.key_changes:
        lines.append("- key_changes:")
        for c in d.key_changes:
            lines.append(f"  - {c}")
    if d.artifacts:
        lines.append("- artifacts:")
        for a in d.artifacts:
            lines.append(f"  - {a.kind}: `{a.ref}` — {a.note}")
    if d.blockers:
        lines.append("- blockers:")
        for blk in d.blockers:
            lines.append(f"  - {blk}")
    return "\n".join(lines)


def _yamlish(d: dict[str, Any], indent: int = 0) -> str:
    pad = "  " * indent
    out: list[str] = []
    for k, v in d.items():
        if isinstance(v, dict):
            out.append(f"{pad}{k}:")
            out.append(_yamlish(v, indent + 1))
        elif isinstance(v, list):
            out.append(f"{pad}{k}: {v}")
        else:
            out.append(f"{pad}{k}: {v}")
    return "\n".join(out)


# ─── final section render ────────────────────────────────────────────────────


_MARKER_PREFIX = "<!-- agent-review:report_date="


def section_marker(date: dt.date) -> str:
    return f"{_MARKER_PREFIX}{date.isoformat()}"


def _render_section(
    date: dt.date,
    narrative_md: str,
    stats: dict[str, Any],
    window_end: dt.datetime | None,
) -> str:
    s = get_settings()
    now = dt.datetime.now(s.tz)
    window_end = window_end or now

    header_dt = now.strftime("%Y-%m-%d %H:%M")
    window_str = (
        f"{date.isoformat()} 00:00 → "
        f"{window_end.astimezone(s.tz).strftime('%H:%M')} {s.tz_name}"
    )
    agents_str = ", ".join(f"{a}×{n}" for a, n in stats["agents"].items()) or "—"
    cost = stats.get("est_total_cost_usd", 0.0)
    proj_count = len(stats["projects"])

    summary_line = (
        f"_window: {window_str} · {stats['sessions']} sessions · "
        f"{proj_count} projects · ~${cost:.2f} · {agents_str}_"
    )

    table = (
        "| sessions | agents | msgs | session out tok | peak ctx | artifacts | blockers | est. cost |\n"
        "|---------:|:-------|-----:|---------------:|--------:|---------:|--------:|---------:|\n"
        f"| {stats['sessions']} | {agents_str} | {stats['messages']} | "
        f"{stats['session_output_tokens_sum']} | {stats['peak_context_tokens_max']} | "
        f"{stats['artifact_count']} | {stats['blocker_count']} | ${cost:.4f} |"
    )

    marker = (
        f"<!-- agent-review:report_date={date.isoformat()} "
        f"generated_at={now.isoformat(timespec='seconds')} -->"
    )

    return (
        f"## agent-review — {header_dt}\n\n"
        f"{summary_line}\n\n"
        f"{narrative_md}\n\n"
        f"### stats\n\n{table}\n\n"
        f"{marker}\n"
    )
