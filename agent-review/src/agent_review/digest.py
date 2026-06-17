"""Stage 2: per-session digest via Claude.

For each session bundle, call the LLM (default Haiku 4.5) with a tool-use
forced response to produce a structured Digest. Cache by (session_id, data_version)
in agent_review.session_digests.
"""

from __future__ import annotations

import json
import re
from importlib.resources import files
from typing import Any, Literal

from psycopg.types.json import Json
from pydantic import BaseModel, Field, model_validator
from tenacity import retry, stop_after_attempt, wait_exponential

from . import llm
from .config import get_settings
from .db import connect
from .extract import SessionBundle, ToolSummary

# ─── schema for the model's response ──────────────────────────────────────────

_XML_TAG = re.compile(r"<[^>]+>")


def _coerce_list(val: Any) -> list:
    """Haiku 4.5 occasionally wraps list values in XML parameter tags or returns
    them as a JSON-encoded string. Coerce back to a plain list."""
    if isinstance(val, list):
        return val
    if not isinstance(val, str):
        return []
    # Strip XML tags: <parameter name="key_changes">...</parameter>
    cleaned = _XML_TAG.sub("", val).strip()
    # Try JSON parse first (handles '["a","b"]' or '[\n  "a"\n]' forms)
    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, list):
            return parsed
    except (json.JSONDecodeError, ValueError):
        pass
    # Fallback: split on newlines, strip bullets/quotes
    lines = [
        ln.strip().lstrip("-•*").strip().strip('"').strip("'")
        for ln in cleaned.splitlines()
        if ln.strip() and not ln.strip().startswith("<")
    ]
    return [ln for ln in lines if ln]


class DigestArtifact(BaseModel):
    kind: str = Field(..., description="commit | pr | branch_push | file_write | file_edit | issue | tag | other")
    ref: str = Field(..., description="commit SHA, PR URL, file path, branch name, etc.")
    note: str = Field(..., description="short human-readable note (e.g. commit message subject)")


class Digest(BaseModel):
    summary: str = Field(..., description="At most 3 sentences. Goal → what got done / stuck.")
    project: str = Field(..., description="Project name (refine if needed).")
    tags: list[str] = Field(default_factory=list, description="0–5 short kebab-case labels.")
    key_changes: list[str] = Field(default_factory=list, description="Concrete changes the agent made.")
    artifacts: list[DigestArtifact] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    outcome: Literal["shipped", "progressed", "stuck", "abandoned", "exploration"]
    confidence: Literal["high", "medium", "low"]

    @model_validator(mode="before")
    @classmethod
    def _coerce_list_fields(cls, values: dict) -> dict:
        for field in ("tags", "key_changes", "blockers"):
            if field in values:
                values[field] = _coerce_list(values[field])
        # artifacts may also come back as a string
        arts = values.get("artifacts")
        if isinstance(arts, str):
            cleaned = _XML_TAG.sub("", arts).strip()
            try:
                parsed = json.loads(cleaned)
                values["artifacts"] = parsed if isinstance(parsed, list) else []
            except (json.JSONDecodeError, ValueError):
                values["artifacts"] = []
        return values


# Tool schema for forced structured output.
SUBMIT_DIGEST_TOOL = {
    "name": "submit_digest",
    "description": "Submit the structured session digest.",
    "input_schema": Digest.model_json_schema(),
}


# ─── prompt loader ────────────────────────────────────────────────────────────


def _load_system_prompt() -> str:
    return files("agent_review.prompts").joinpath("digest_system.md").read_text()


# ─── public entry points ──────────────────────────────────────────────────────


def get_or_create_digest(bundle: SessionBundle, *, force: bool = False) -> Digest:
    """Cache-aware digest. Reads from agent_review.session_digests when
    (session_id, data_version) matches, otherwise calls the LLM and upserts."""
    digest, _, _ = get_or_create_digest_result(bundle, force=force)
    return digest


def get_or_create_digest_result(
    bundle: SessionBundle,
    *,
    force: bool = False,
    persist: bool = True,
) -> tuple[Digest, dict[str, int], bool]:
    """Cache-aware digest with token usage.

    Returns (digest, usage, fresh). When persist=False, fresh LLM results are
    returned without writing session_digests, which keeps CLI dry-runs dry.
    """
    if not force:
        cached = _load_cached_with_usage(bundle.session_id, bundle.data_version)
        if cached is not None:
            digest, usage = cached
            return digest, usage, False
    digest, usage = _call_llm(bundle)
    if persist:
        _upsert(bundle, digest, usage)
    return digest, usage, True


def get_or_create_digests(bundles: list[SessionBundle], *, force: bool = False) -> list[Digest]:
    """Convenience: digest a list of bundles in order, caching per-session."""
    out: list[Digest] = []
    for b in bundles:
        out.append(get_or_create_digest(b, force=force))
    return out


# ─── DB cache ─────────────────────────────────────────────────────────────────


def _load_cached(session_id: str, data_version: int) -> Digest | None:
    cached = _load_cached_with_usage(session_id, data_version)
    if cached is None:
        return None
    digest, _ = cached
    return digest


def _load_cached_with_usage(
    session_id: str,
    data_version: int,
) -> tuple[Digest, dict[str, int]] | None:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT digest, prompt_tokens, output_tokens, cached_tokens
              FROM agent_review.session_digests
             WHERE session_id = %s AND data_version = %s
            """,
            (session_id, data_version),
        )
        row = cur.fetchone()
    if not row:
        return None
    return Digest.model_validate(row["digest"]), {
        "input_tokens": row["prompt_tokens"],
        "output_tokens": row["output_tokens"],
        "cache_read_input_tokens": row["cached_tokens"],
    }


def _upsert(bundle: SessionBundle, digest: Digest, usage: dict[str, int]) -> None:
    s = get_settings()
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO agent_review.session_digests
                (session_id, data_version, model, prompt_tokens, output_tokens,
                 cached_tokens, digest, generated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, now())
            ON CONFLICT (session_id) DO UPDATE SET
                data_version  = EXCLUDED.data_version,
                model         = EXCLUDED.model,
                prompt_tokens = EXCLUDED.prompt_tokens,
                output_tokens = EXCLUDED.output_tokens,
                cached_tokens = EXCLUDED.cached_tokens,
                digest        = EXCLUDED.digest,
                generated_at  = now()
            """,
            (
                bundle.session_id,
                bundle.data_version,
                s.model_digest,
                usage.get("input_tokens", 0),
                usage.get("output_tokens", 0),
                usage.get("cache_read_input_tokens", 0),
                Json(digest.model_dump()),
            ),
        )
        conn.commit()


# ─── LLM call ────────────────────────────────────────────────────────────────


@retry(stop=stop_after_attempt(4), wait=wait_exponential(multiplier=2, min=2, max=30))
def _call_llm(bundle: SessionBundle) -> tuple[Digest, dict[str, int]]:
    s = get_settings()
    result = llm.complete(
        model=s.model_digest,
        system_prompt=_load_system_prompt(),
        user_content=_render_user_payload(bundle),
        max_tokens=4096,
        tool=SUBMIT_DIGEST_TOOL,
        settings=s,
    )
    if result.structured is None:
        raise RuntimeError(
            f"No structured digest in response for session {bundle.session_id} "
            f"(model={s.model_digest}, backend={s.llm_backend})"
        )
    return Digest.model_validate(result.structured), result.usage


# ─── render the user message ─────────────────────────────────────────────────


def _render_user_payload(b: SessionBundle) -> str:
    parts: list[str] = []
    parts.append("# session metadata")
    parts.append(
        f"- session_id: {b.session_id}\n"
        f"- agent: {b.agent}\n"
        f"- machine: {b.machine}\n"
        f"- project: {b.project}  (source: {b.project_source})\n"
        f"- cwd: {b.cwd or '(none)'}\n"
        f"- git_branch: {b.git_branch or '(none)'}\n"
        f"- started_at: {b.started_at.isoformat()}\n"
        f"- ended_at: {b.ended_at.isoformat() if b.ended_at else '(none)'}\n"
        f"- duration_minutes: {b.duration_minutes}\n"
        f"- message_count: {b.message_count}  (user: {b.user_message_count})\n"
        f"- outcome: {b.outcome}  (confidence: {b.outcome_confidence})\n"
        f"- health_grade: {b.health_grade or '?'}\n"
        f"- termination_status: {b.termination_status or '?'}\n"
        f"- is_truncated: {b.is_truncated}\n"
        f"- peak_context_tokens: {b.peak_context_tokens}\n"
        f"- total_output_tokens: {b.total_output_tokens}"
    )

    parts.append("\n# tool summary")
    parts.append(_render_tool_summary(b.tool_summary))

    if b.artifacts:
        parts.append("\n# extracted artifacts (deterministic)")
        for a in b.artifacts:
            parts.append(f"- {a['kind']}: `{a['ref']}` — {a['note']}")

    if b.subagents:
        parts.append(f"\n# subagents folded in ({len(b.subagents)})")
        for sub in b.subagents:
            parts.append(
                f"- {sub.agent} ({sub.message_count} msgs, "
                f"{sub.tool_summary.total_calls} tool calls): "
                f"{(sub.first_message[:120] + '…') if len(sub.first_message) > 120 else sub.first_message}"
            )
        parts.append("\n# subagent transcripts (compressed)")
        for sub in b.subagents:
            parts.append(
                f"\n## subagent {sub.session_id}\n"
                f"- agent: {sub.agent}\n"
                f"- project: {sub.project}  (source: {sub.project_source})\n"
                f"- cwd: {sub.cwd or '(none)'}\n"
                f"- outcome: {sub.outcome}  (confidence: {sub.outcome_confidence})\n"
                f"- tool calls: {sub.tool_summary.total_calls}\n"
                f"{_render_tool_summary(sub.tool_summary)}\n\n"
                f"{sub.transcript_text or '(empty)'}"
            )

    parts.append("\n# transcript (compressed)")
    parts.append(b.transcript_text or "(empty)")

    return "\n".join(parts)


def _render_tool_summary(s: ToolSummary) -> str:
    lines = [f"- total tool calls: {s.total_calls}"]
    if s.by_category:
        cats = ", ".join(f"{k}={v}" for k, v in sorted(s.by_category.items(), key=lambda kv: -kv[1]))
        lines.append(f"- by category: {cats}")
    if s.top_bash_commands:
        lines.append("- top bash commands:")
        for cmd in s.top_bash_commands:
            lines.append(f"    `{cmd}`")
    if s.files_touched:
        lines.append("- files touched:")
        for f in s.files_touched:
            lines.append(f"    `{f}`")
    return "\n".join(lines)


# ─── pricing helper (used by daily synthesis cost rollup) ────────────────────


def fetch_pricing() -> dict[str, dict[str, float]]:
    """Read {pg_schema}.model_pricing into {pattern: {input, output, cache_read,
    cache_creation}}."""
    schema = get_settings().pg_schema
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT model_pattern, input_per_mtok, output_per_mtok, "
            f"cache_creation_per_mtok, cache_read_per_mtok FROM {schema}.model_pricing"
        )
        rows = cur.fetchall()
    return {
        r["model_pattern"]: {
            "input": r["input_per_mtok"],
            "output": r["output_per_mtok"],
            "cache_creation": r["cache_creation_per_mtok"],
            "cache_read": r["cache_read_per_mtok"],
        }
        for r in rows
    }


def estimate_cost(model: str, usage: dict[str, int], pricing: dict[str, dict[str, float]]) -> float:
    """Rough cost estimate for a single LLM call. Matches model name against
    patterns longest-prefix; falls back to 0.0 if no match."""
    p = _match_pricing(model, pricing)
    if not p:
        return 0.0
    return (
        usage.get("input_tokens", 0) / 1e6 * p["input"]
        + usage.get("output_tokens", 0) / 1e6 * p["output"]
        + usage.get("cache_creation_input_tokens", 0) / 1e6 * p["cache_creation"]
        + usage.get("cache_read_input_tokens", 0) / 1e6 * p["cache_read"]
    )


def _match_pricing(model: str, pricing: dict[str, dict[str, float]]) -> dict[str, float] | None:
    candidates = [pat for pat in pricing if model.startswith(pat) or pat in model]
    if not candidates:
        return None
    best = max(candidates, key=len)
    return pricing[best]
