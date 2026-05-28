"""Compare candidate models for the per-session digest stage.

Default lineup: Haiku 4.5 (baseline) vs gpt-4.1-mini vs gemini-2.5-flash-lite.
Each model gets the same SessionBundle, same system prompt, same forced
tool-call schema. Outputs a markdown report aimed at building intuition for
how these workhorse models behave on a real automated workflow — not just
picking a winner.

Run from agent-review/ dir:
    LLM_API_KEY=$ANTHROPIC_API_KEY uv run python scripts/compare_digest_models.py \\
        --days 3 --limit 10 --out /tmp/digest_compare.md

Required env: LLM_API_KEY (Anthropic), OPENAI_API_KEY, GEMINI_API_KEY.
Gemini uses its OpenAI-compatible endpoint so we reuse the OpenAI SDK.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import random
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import click
from anthropic import Anthropic
from pydantic import ValidationError

# Make the script runnable without installing the package separately.
_PKG_SRC = Path(__file__).resolve().parents[1] / "src"
if _PKG_SRC.is_dir() and str(_PKG_SRC) not in sys.path:
    sys.path.insert(0, str(_PKG_SRC))

from agent_review.config import get_settings  # noqa: E402
from agent_review.digest import (  # noqa: E402
    SUBMIT_DIGEST_TOOL,
    Digest,
    _load_system_prompt,
    _render_user_payload,
)
from agent_review.extract import SessionBundle, extract_day  # noqa: E402

# Per-Mtok USD. Anthropic cache pricing only applies to ephemeral cache_control.
PRICING: dict[str, dict[str, float]] = {
    "claude-haiku-4-5-20251001": {
        "input": 1.00, "output": 5.00, "cache_read": 0.10, "cache_creation": 1.25,
    },
    "gpt-4.1-mini": {
        "input": 0.40, "output": 1.60, "cache_read": 0.10, "cache_creation": 0.0,
    },
    "gpt-4o-mini": {
        "input": 0.15, "output": 0.60, "cache_read": 0.075, "cache_creation": 0.0,
    },
    "gemini-2.5-flash-lite": {
        "input": 0.10, "output": 0.40, "cache_read": 0.025, "cache_creation": 0.0,
    },
    "gemini-2.5-flash": {
        "input": 0.30, "output": 2.50, "cache_read": 0.075, "cache_creation": 0.0,
    },
}

GEMINI_OPENAI_BASE = "https://generativelanguage.googleapis.com/v1beta/openai/"


@dataclass
class CallResult:
    digest: Digest | None
    raw_args: dict[str, Any] | None  # raw tool-call arguments (pre-validation)
    extra_text: str = ""  # any non-tool text the model emitted alongside the call
    usage: dict[str, int] = field(default_factory=dict)
    wall_ms: int = 0
    error: str | None = None
    stop_reason: str | None = None

    @property
    def ok(self) -> bool:
        return self.digest is not None


@dataclass
class Provider:
    model: str       # unique key + display label (may carry a #native/#compat suffix)
    api_model: str   # bare model id sent to the API + used for pricing
    family: str      # "anthropic" | "openai" | "gemini_native"
    base_url: str | None = None
    api_key_env: str = ""


def _pricing_key(model: str) -> str:
    return model.split("#", 1)[0]


def cost(model: str, usage: dict[str, int]) -> float:
    p = PRICING.get(_pricing_key(model), {})
    if not p:
        return 0.0
    return (
        usage.get("input_tokens", 0) / 1e6 * p["input"]
        + usage.get("output_tokens", 0) / 1e6 * p["output"]
        + usage.get("cache_read_input_tokens", 0) / 1e6 * p["cache_read"]
        + usage.get("cache_creation_input_tokens", 0) / 1e6 * p["cache_creation"]
    )


# ─── provider calls ──────────────────────────────────────────────────────────


def call_anthropic(client: Anthropic, model: str, bundle: SessionBundle) -> CallResult:
    payload = _render_user_payload(bundle)
    t0 = time.perf_counter()
    try:
        resp = client.messages.create(
            model=model,
            max_tokens=4096,
            system=[
                {
                    "type": "text",
                    "text": _load_system_prompt(),
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            tools=[SUBMIT_DIGEST_TOOL],
            tool_choice={"type": "tool", "name": "submit_digest"},
            messages=[{"role": "user", "content": payload}],
        )
    except Exception as e:
        return CallResult(None, None, error=f"api: {e}",
                          wall_ms=int((time.perf_counter() - t0) * 1000))
    wall_ms = int((time.perf_counter() - t0) * 1000)

    tool_block = next((b for b in resp.content if getattr(b, "type", None) == "tool_use"), None)
    extra_text = " ".join(
        b.text for b in resp.content
        if getattr(b, "type", None) == "text" and getattr(b, "text", "")
    ).strip()
    usage = {
        "input_tokens": resp.usage.input_tokens,
        "output_tokens": resp.usage.output_tokens,
        "cache_read_input_tokens": getattr(resp.usage, "cache_read_input_tokens", 0) or 0,
        "cache_creation_input_tokens": getattr(resp.usage, "cache_creation_input_tokens", 0) or 0,
    }
    stop = getattr(resp, "stop_reason", None)
    if tool_block is None:
        return CallResult(None, None, extra_text=extra_text, usage=usage, wall_ms=wall_ms,
                          stop_reason=stop, error=f"no tool_use block (stop={stop})")
    raw = dict(tool_block.input)
    try:
        digest = Digest.model_validate(raw)
    except ValidationError as e:
        return CallResult(None, raw, extra_text=extra_text, usage=usage, wall_ms=wall_ms,
                          stop_reason=stop, error=f"schema: {_short_validation_err(e)}")
    return CallResult(digest, raw, extra_text=extra_text, usage=usage, wall_ms=wall_ms, stop_reason=stop)


def call_openai_like(client, model: str, bundle: SessionBundle) -> CallResult:
    tool = {
        "type": "function",
        "function": {
            "name": SUBMIT_DIGEST_TOOL["name"],
            "description": SUBMIT_DIGEST_TOOL["description"],
            "parameters": SUBMIT_DIGEST_TOOL["input_schema"],
        },
    }
    payload = _render_user_payload(bundle)
    t0 = time.perf_counter()
    try:
        resp = client.chat.completions.create(
            model=model,
            max_tokens=4096,
            tools=[tool],
            tool_choice={"type": "function", "function": {"name": "submit_digest"}},
            messages=[
                {"role": "system", "content": _load_system_prompt()},
                {"role": "user", "content": payload},
            ],
        )
    except Exception as e:
        return CallResult(None, None, error=f"api: {e}",
                          wall_ms=int((time.perf_counter() - t0) * 1000))
    wall_ms = int((time.perf_counter() - t0) * 1000)

    u = resp.usage
    cached = 0
    details = getattr(u, "prompt_tokens_details", None)
    if details is not None:
        cached = getattr(details, "cached_tokens", 0) or 0
    usage = {
        "input_tokens": max(u.prompt_tokens - cached, 0),
        "output_tokens": u.completion_tokens,
        "cache_read_input_tokens": cached,
        "cache_creation_input_tokens": 0,
    }

    msg = resp.choices[0].message
    stop = resp.choices[0].finish_reason
    extra_text = (msg.content or "").strip()
    tool_calls = msg.tool_calls or []
    if not tool_calls:
        return CallResult(None, None, extra_text=extra_text, usage=usage, wall_ms=wall_ms,
                          stop_reason=stop, error=f"no tool_call (finish={stop})")
    raw_args_str = tool_calls[0].function.arguments
    try:
        args = json.loads(raw_args_str)
    except json.JSONDecodeError as e:
        return CallResult(None, None, extra_text=extra_text, usage=usage, wall_ms=wall_ms,
                          stop_reason=stop, error=f"json: {e}")
    try:
        digest = Digest.model_validate(args)
    except ValidationError as e:
        return CallResult(None, args, extra_text=extra_text, usage=usage, wall_ms=wall_ms,
                          stop_reason=stop, error=f"schema: {_short_validation_err(e)}")
    return CallResult(digest, args, extra_text=extra_text, usage=usage, wall_ms=wall_ms, stop_reason=stop)


def _short_validation_err(e: ValidationError) -> str:
    out = []
    for err in e.errors()[:3]:
        loc = ".".join(str(p) for p in err["loc"])
        out.append(f"{loc}={err['type']}")
    extra = "" if len(e.errors()) <= 3 else f" (+{len(e.errors()) - 3} more)"
    return "; ".join(out) + extra


def _inline_schema(schema: dict) -> dict:
    """Resolve $ref/$defs into a self-contained schema. Gemini's native
    FunctionDeclaration rejects $ref, so nested object types must be inlined."""
    defs = schema.get("$defs", {})

    def resolve(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                ref = node["$ref"].rsplit("/", 1)[-1]
                return resolve(dict(defs[ref]))
            return {k: resolve(v) for k, v in node.items() if k != "$defs"}
        if isinstance(node, list):
            return [resolve(v) for v in node]
        return node

    out = resolve(schema)
    out.pop("$defs", None)
    return out


def call_gemini_native(client, model: str, bundle: SessionBundle) -> CallResult:
    """Gemini via the native google-genai SDK with forced function calling and
    an inlined (no-$ref) schema."""
    from google.genai import types

    params = _inline_schema(SUBMIT_DIGEST_TOOL["input_schema"])
    tool = types.Tool(function_declarations=[
        types.FunctionDeclaration(
            name=SUBMIT_DIGEST_TOOL["name"],
            description=SUBMIT_DIGEST_TOOL["description"],
            parameters=params,
        )
    ])
    config = types.GenerateContentConfig(
        system_instruction=_load_system_prompt(),
        tools=[tool],
        tool_config=types.ToolConfig(
            function_calling_config=types.FunctionCallingConfig(
                mode="ANY", allowed_function_names=["submit_digest"]
            )
        ),
        max_output_tokens=4096,
        temperature=0,
    )
    payload = _render_user_payload(bundle)
    t0 = time.perf_counter()
    try:
        resp = client.models.generate_content(model=model, contents=payload, config=config)
    except Exception as e:
        return CallResult(None, None, error=f"api: {e}",
                          wall_ms=int((time.perf_counter() - t0) * 1000))
    wall_ms = int((time.perf_counter() - t0) * 1000)

    um = getattr(resp, "usage_metadata", None)
    cached = getattr(um, "cached_content_token_count", 0) or 0 if um else 0
    prompt_toks = getattr(um, "prompt_token_count", 0) or 0 if um else 0
    usage = {
        "input_tokens": max(prompt_toks - cached, 0),
        "output_tokens": (getattr(um, "candidates_token_count", 0) or 0) if um else 0,
        "cache_read_input_tokens": cached,
        "cache_creation_input_tokens": 0,
    }

    cand = (resp.candidates or [None])[0]
    stop = str(getattr(cand, "finish_reason", None)) if cand else None
    fc = None
    extra_text = ""
    if cand and cand.content and cand.content.parts:
        for part in cand.content.parts:
            if getattr(part, "function_call", None):
                fc = part.function_call
            elif getattr(part, "text", None):
                extra_text += part.text
    extra_text = extra_text.strip()
    if fc is None:
        return CallResult(None, None, extra_text=extra_text, usage=usage, wall_ms=wall_ms,
                          stop_reason=stop, error=f"no function_call (finish={stop})")
    # fc.args is a dict-like; round-trip through JSON to get plain python types.
    try:
        args = json.loads(json.dumps(dict(fc.args)))
    except (TypeError, ValueError) as e:
        return CallResult(None, None, extra_text=extra_text, usage=usage, wall_ms=wall_ms,
                          stop_reason=stop, error=f"args: {e}")
    try:
        digest = Digest.model_validate(args)
    except ValidationError as e:
        return CallResult(None, args, extra_text=extra_text, usage=usage, wall_ms=wall_ms,
                          stop_reason=stop, error=f"schema: {_short_validation_err(e)}")
    return CallResult(digest, args, extra_text=extra_text, usage=usage, wall_ms=wall_ms, stop_reason=stop)


# ─── judge ───────────────────────────────────────────────────────────────────

JUDGE_TOOL = {
    "name": "submit_ranking",
    "description": "Submit your blind ranking of the candidate digests.",
    "input_schema": {
        "type": "object",
        "properties": {
            "ranking": {
                "type": "array",
                "description": "Candidate labels (A, B, C, ...) from best to worst. Ties allowed by repeating.",
                "items": {"type": "string"},
            },
            "accuracy_best": {"type": "string"},
            "specificity_best": {"type": "string"},
            "concision_best": {"type": "string"},
            "reasoning": {"type": "string"},
        },
        "required": ["ranking", "accuracy_best", "specificity_best", "concision_best", "reasoning"],
    },
}

JUDGE_SYSTEM = """You are blindly comparing structured digests of the same agent session, labeled A, B, C, ...
You see the same session metadata + compressed transcript that all candidates saw.

Judge on:
1. Accuracy — does it correctly identify what the agent did, the outcome, the project?
2. Specificity — concrete artifacts (commits, files, PRs) over vague summary text.
3. Concision — surfaces blockers and key changes without padding.

Rank ALL candidates best to worst. Ties allowed (repeat a label). Per-axis: name single best.
Be terse in reasoning (2-4 sentences). Reference candidates by their LETTER, not by guessed model."""


def call_judge(client: Anthropic, judge_model: str, bundle: SessionBundle,
               labeled: list[tuple[str, Digest]]) -> dict[str, Any] | None:
    parts = ["# session context (same for all candidates)", _render_user_payload(bundle), ""]
    for label, d in labeled:
        parts.append(f"# digest {label}")
        parts.append("```json")
        parts.append(json.dumps(d.model_dump(), indent=2))
        parts.append("```")
        parts.append("")
    payload = "\n".join(parts)
    try:
        resp = client.messages.create(
            model=judge_model,
            max_tokens=1024,
            system=[{"type": "text", "text": JUDGE_SYSTEM,
                     "cache_control": {"type": "ephemeral"}}],
            tools=[JUDGE_TOOL],
            tool_choice={"type": "tool", "name": "submit_ranking"},
            messages=[{"role": "user", "content": payload}],
        )
    except Exception as e:
        return {"error": str(e)}
    tool_block = next((b for b in resp.content if getattr(b, "type", None) == "tool_use"), None)
    if tool_block is None:
        return None
    out = dict(tool_block.input)
    out["_usage"] = {
        "input_tokens": resp.usage.input_tokens,
        "output_tokens": resp.usage.output_tokens,
    }
    return out


# ─── sampling ────────────────────────────────────────────────────────────────


def collect_bundles(days: int, limit: int) -> list[SessionBundle]:
    today = dt.date.today()
    bundles: list[SessionBundle] = []
    for delta in range(days):
        date = today - dt.timedelta(days=delta)
        bundles.extend(extract_day(date))
        if len(bundles) >= limit:
            break
    bundles.sort(key=lambda b: b.started_at, reverse=True)
    return bundles[:limit]


# ─── report ──────────────────────────────────────────────────────────────────


def _mean(xs: list[int | float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def render_report(samples: list[dict], providers: list[Provider],
                  judge_model: str | None) -> str:
    n = len(samples)
    lines: list[str] = []
    lines.append(f"# Digest model comparison ({len(providers)}-way)\n")
    lines.append(f"_Generated {dt.datetime.now().isoformat(timespec='seconds')}_  ·  Samples: **{n}**\n")
    lines.append("**Candidates:**")
    for p in providers:
        lines.append(f"- `{p.model}` ({p.family})")
    lines.append("")
    lines.append("_Judge labels (A/B/C) are randomized per sample to keep the judge blind; the per-sample sections de-blind inline._\n")

    # ─── conformance ───
    lines.append("## Schema conformance\n")
    lines.append("| Model | Parsed OK | Schema failures | API/no-tool failures |")
    lines.append("|---|---:|---:|---:|")
    for p in providers:
        ok = sum(1 for s in samples if s["results"][p.model].ok)
        schema_fail = sum(
            1 for s in samples
            if not s["results"][p.model].ok
            and (s["results"][p.model].error or "").startswith("schema")
        )
        other_fail = n - ok - schema_fail
        lines.append(f"| `{p.model}` | {ok}/{n} | {schema_fail} | {other_fail} |")
    lines.append("")

    # ─── cost/tokens ───
    lines.append("## Cost & token totals (across all samples)\n")
    lines.append("| Model | input | output | cache_read | cache_create | total $ | $/session |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|")
    for p in providers:
        tin = sum(s["results"][p.model].usage.get("input_tokens", 0) for s in samples)
        tout = sum(s["results"][p.model].usage.get("output_tokens", 0) for s in samples)
        tcr = sum(s["results"][p.model].usage.get("cache_read_input_tokens", 0) for s in samples)
        tcc = sum(s["results"][p.model].usage.get("cache_creation_input_tokens", 0) for s in samples)
        total = sum(cost(p.model, s["results"][p.model].usage) for s in samples)
        per = total / n if n else 0.0
        lines.append(
            f"| `{p.model}` | {tin:,} | {tout:,} | {tcr:,} | {tcc:,} | ${total:.4f} | ${per:.5f} |"
        )
    lines.append("")
    baseline = providers[0].model
    base_cost = sum(cost(baseline, s["results"][baseline].usage) for s in samples)
    if base_cost > 0:
        lines.append("**Relative to baseline:**")
        for p in providers[1:]:
            c = sum(cost(p.model, s["results"][p.model].usage) for s in samples)
            if c > 0:
                ratio = base_cost / c
                lines.append(f"- `{p.model}` is **{ratio:.2f}× cheaper** than `{baseline}` on this sample")
        lines.append("")

    # ─── verbosity ───
    lines.append("## Output verbosity (mean output tokens per session)\n")
    lines.append("| Model | mean out tokens | mean key_changes | mean artifacts | mean blockers |")
    lines.append("|---|---:|---:|---:|---:|")
    for p in providers:
        rs = [s["results"][p.model] for s in samples if s["results"][p.model].ok]
        out_toks = [r.usage.get("output_tokens", 0) for r in rs]
        kc = [len(r.digest.key_changes) for r in rs]
        arts = [len(r.digest.artifacts) for r in rs]
        blk = [len(r.digest.blockers) for r in rs]
        lines.append(
            f"| `{p.model}` | {_mean(out_toks):.0f} | {_mean(kc):.1f} | {_mean(arts):.1f} | {_mean(blk):.1f} |"
        )
    lines.append("")

    # ─── latency ───
    lines.append("## Latency (ms per call)\n")
    lines.append("| Model | mean | min | max |")
    lines.append("|---|---:|---:|---:|")
    for p in providers:
        ls = [s["results"][p.model].wall_ms for s in samples if s["results"][p.model].wall_ms]
        if ls:
            lines.append(f"| `{p.model}` | {_mean(ls):.0f} | {min(ls)} | {max(ls)} |")
    lines.append("")

    # ─── behavioral notes: emitted-alongside text, stop reasons, schema-fail fields ───
    lines.append("## Behavioral notes (subtleties worth seeing)\n")
    for p in providers:
        rs = [s["results"][p.model] for s in samples]
        chatty = sum(1 for r in rs if r.extra_text)
        chatty_sample = next((r.extra_text for r in rs if r.extra_text), "")
        stops = {}
        for r in rs:
            stops[r.stop_reason or "none"] = stops.get(r.stop_reason or "none", 0) + 1
        schema_errs = [r.error for r in rs if r.error and r.error.startswith("schema")]
        lines.append(f"### `{p.model}`")
        lines.append(f"- emitted non-tool text alongside tool call: **{chatty}/{n}** times")
        if chatty_sample:
            sample = chatty_sample[:200].replace("\n", " ")
            suffix = "…" if len(chatty_sample) > 200 else ""
            lines.append(f"  - first example: \"{sample}{suffix}\"")
        lines.append(f"- stop reasons: {dict(stops)}")
        if schema_errs:
            lines.append(f"- schema failures ({len(schema_errs)}):")
            for e in schema_errs[:5]:
                lines.append(f"  - {e}")
        lines.append("")

    # ─── judge tally ───
    if judge_model:
        verdicts = [s["judge"] for s in samples if s.get("judge") and "error" not in s["judge"]]
        lines.append(f"## Judge tally ({judge_model}, blind labels)\n")
        lines.append(f"Verdicts collected: {len(verdicts)} / {n}\n")
        if verdicts:
            # First-place counts (de-blinded)
            first_place: dict[str, int] = {p.model: 0 for p in providers}
            for s in samples:
                v = s.get("judge")
                if not v or "error" in v or not v.get("ranking"):
                    continue
                first_label = v["ranking"][0]
                model = s["label_to_model"].get(first_label)
                if model:
                    first_place[model] = first_place.get(model, 0) + 1
            lines.append("**First-place counts (de-blinded):**")
            for p in providers:
                lines.append(f"- `{p.model}`: {first_place.get(p.model, 0)}")
            lines.append("")
            # Per-axis wins
            for axis in ("accuracy_best", "specificity_best", "concision_best"):
                tally: dict[str, int] = {p.model: 0 for p in providers}
                for s in samples:
                    v = s.get("judge")
                    if not v or "error" in v:
                        continue
                    lbl = v.get(axis)
                    if lbl:
                        m = s["label_to_model"].get(lbl)
                        if m:
                            tally[m] = tally.get(m, 0) + 1
                lines.append(f"**{axis}:**")
                for p in providers:
                    lines.append(f"- `{p.model}`: {tally.get(p.model, 0)}")
                lines.append("")

    # ─── per-sample ───
    lines.append("## Per-sample side-by-side\n")
    for i, s in enumerate(samples, 1):
        b = s["bundle"]
        lines.append(f"### {i}. `{b.session_id[:8]}` — {b.project}  ({b.agent}, {b.duration_minutes or 0}m, {b.message_count} msgs)")
        lines.append(f"- started: {b.started_at.isoformat()}  ·  outcome (heuristic): {b.outcome}")
        lines.append("")
        for p in providers:
            label = s["model_to_label"][p.model]
            r: CallResult = s["results"][p.model]
            header = f"**{label} = `{p.model}`** — "
            if not r.ok:
                lines.append(header + f"❌ {r.error}")
                if r.extra_text:
                    sample = r.extra_text[:300].replace("\n", " ")
                    lines.append(f"  - emitted text: \"{sample}{'…' if len(r.extra_text) > 300 else ''}\"")
                if r.raw_args is not None:
                    lines.append(f"  - raw_args keys: {list(r.raw_args.keys())}")
                lines.append("")
                continue
            d = r.digest
            lines.append(
                header +
                f"{r.wall_ms}ms · in={r.usage.get('input_tokens', 0)} out={r.usage.get('output_tokens', 0)}"
                f" · ${cost(p.model, r.usage):.5f}"
            )
            lines.append(f"- summary: {d.summary}")
            lines.append(f"- project: `{d.project}` · outcome: {d.outcome} ({d.confidence})")
            if d.tags:
                lines.append(f"- tags: {', '.join(d.tags)}")
            if d.key_changes:
                lines.append("- key_changes:")
                for kc in d.key_changes:
                    lines.append(f"  - {kc}")
            if d.artifacts:
                lines.append(f"- artifacts ({len(d.artifacts)}):")
                for a in d.artifacts:
                    lines.append(f"  - `{a.kind}` {a.ref} — {a.note}")
            if d.blockers:
                lines.append(f"- blockers: {'; '.join(d.blockers)}")
            if r.extra_text:
                preview = r.extra_text[:200].replace("\n", " ")
                lines.append(f"- 💬 emitted alongside tool call: \"{preview}{'…' if len(r.extra_text) > 200 else ''}\"")
            lines.append("")
        if s.get("judge") and "error" not in s["judge"]:
            v = s["judge"]
            ranking = v.get("ranking", [])
            de_blind = lambda lbl: s["label_to_model"].get(lbl, lbl)  # noqa: E731
            ranked = " > ".join(f"{lbl}(`{de_blind(lbl)}`)" for lbl in ranking)
            lines.append(f"**Judge ranking:** {ranked}")
            lines.append(f"- accuracy: {v.get('accuracy_best')} (`{de_blind(v.get('accuracy_best'))}`)")
            lines.append(f"- specificity: {v.get('specificity_best')} (`{de_blind(v.get('specificity_best'))}`)")
            lines.append(f"- concision: {v.get('concision_best')} (`{de_blind(v.get('concision_best'))}`)")
            lines.append(f"- reasoning: {v.get('reasoning', '')}")
            lines.append("")
        lines.append("---\n")
    return "\n".join(lines)


# ─── main ────────────────────────────────────────────────────────────────────


def build_providers(model_specs: list[str]) -> list[Provider]:
    """Map a model spec → Provider config.

    Spec forms:
      claude-...                     Anthropic native
      gpt-... / o...                 OpenAI native
      gemini-...                     Gemini via OpenAI-compat endpoint
      gemini-native:gemini-...       Gemini via native google-genai SDK
    """
    out: list[Provider] = []
    for spec in model_specs:
        if spec.startswith("gemini-native:"):
            bare = spec.split(":", 1)[1]
            out.append(Provider(model=f"{bare}#native", api_model=bare,
                                family="gemini_native", api_key_env="GEMINI_API_KEY"))
        elif spec.startswith("claude-"):
            out.append(Provider(model=spec, api_model=spec, family="anthropic",
                                api_key_env="LLM_API_KEY"))
        elif spec.startswith("gemini-"):
            out.append(Provider(model=spec, api_model=spec, family="openai",
                                base_url=GEMINI_OPENAI_BASE, api_key_env="GEMINI_API_KEY"))
        elif spec.startswith("gpt-") or spec.startswith("o"):
            out.append(Provider(model=spec, api_model=spec, family="openai",
                                base_url=None, api_key_env="OPENAI_API_KEY"))
        else:
            raise click.ClickException(f"unknown model family for '{spec}' — extend build_providers()")
    return out


@click.command()
@click.option("--days", type=int, default=3, help="How many days back to sample from.")
@click.option("--limit", type=int, default=10, help="Max sessions to compare.")
@click.option("--out", type=click.Path(path_type=Path),
              default=Path("/tmp/digest_compare.md"),
              help="Markdown report output path.")
@click.option("--judge/--no-judge", default=True, help="Run Sonnet blind ranking judge.")
@click.option("--models", default="claude-haiku-4-5-20251001,gpt-4.1-mini,gemini-2.5-flash-lite",
              help="Comma-separated model ids. First entry is treated as baseline.")
@click.option("--seed", type=int, default=42, help="RNG seed for blind label assignment.")
def main(days: int, limit: int, out: Path, judge: bool, models: str, seed: int) -> None:
    try:
        from openai import OpenAI
    except ImportError:
        click.echo("openai package not installed. Run: uv add --dev openai", err=True)
        sys.exit(2)

    model_specs = [m.strip() for m in models.split(",") if m.strip()]
    providers = build_providers(model_specs)

    # Validate required keys
    needed_keys = {p.api_key_env for p in providers}
    for k in needed_keys:
        if not os.environ.get(k):
            click.echo(f"{k} not set in env", err=True)
            sys.exit(2)

    rng = random.Random(seed)
    s = get_settings()

    # Build clients per family. One Anthropic client, one OpenAI client per base_url.
    anthropic_client = Anthropic(
        api_key=s.llm_api_key.get_secret_value(),
        base_url=s.llm_base_url,
    )
    openai_clients: dict[str | None, Any] = {}
    genai_client = None

    def caller_for(p: Provider) -> Callable[[SessionBundle], CallResult]:
        nonlocal genai_client
        if p.family == "anthropic":
            return lambda b: call_anthropic(anthropic_client, p.api_model, b)
        if p.family == "gemini_native":
            if genai_client is None:
                from google import genai
                genai_client = genai.Client(api_key=os.environ[p.api_key_env])
            return lambda b: call_gemini_native(genai_client, p.api_model, b)
        # openai-family (real OpenAI or Gemini-via-compat)
        key_val = os.environ[p.api_key_env]
        client = openai_clients.get(p.base_url)
        if client is None:
            client = OpenAI(api_key=key_val, base_url=p.base_url) if p.base_url \
                else OpenAI(api_key=key_val)
            openai_clients[p.base_url] = client
        return lambda b: call_openai_like(client, p.api_model, b)

    callers = {p.model: caller_for(p) for p in providers}

    click.echo(f"collecting up to {limit} bundles from last {days} day(s)...", err=True)
    bundles = collect_bundles(days, limit)
    click.echo(f"got {len(bundles)} bundles", err=True)
    if not bundles:
        click.echo("no bundles to compare", err=True)
        sys.exit(1)
    click.echo(f"running {len(providers)} models × {len(bundles)} sessions"
               f" = {len(providers) * len(bundles)} calls"
               + (f" + {len(bundles)} judge calls" if judge else ""), err=True)

    samples: list[dict] = []
    for i, b in enumerate(bundles, 1):
        click.echo(f"\n[{i}/{len(bundles)}] {b.session_id[:8]} {b.project}", err=True)
        results: dict[str, CallResult] = {}
        for p in providers:
            r = callers[p.model](b)
            results[p.model] = r
            status = "ok" if r.ok else "FAIL"
            note = f" ({r.error})" if r.error else ""
            click.echo(f"  {p.model:38s} {status:4s} {r.wall_ms:5d}ms{note}", err=True)

        # Shuffle labels for blind judge.
        shuffled = list(providers)
        rng.shuffle(shuffled)
        label_to_model = {chr(65 + idx): p.model for idx, p in enumerate(shuffled)}
        model_to_label = {m: lbl for lbl, m in label_to_model.items()}

        verdict = None
        if judge:
            labeled_digests = [
                (lbl, results[m].digest) for lbl, m in label_to_model.items()
                if results[m].ok
            ]
            if len(labeled_digests) >= 2:
                verdict = call_judge(anthropic_client, s.model_synth, b, labeled_digests)
                if verdict and "error" not in verdict and verdict.get("ranking"):
                    ranking = " > ".join(verdict["ranking"])
                    click.echo(f"  judge: {ranking}", err=True)
                else:
                    click.echo(f"  judge: failed ({verdict})", err=True)

        samples.append({
            "bundle": b,
            "results": results,
            "label_to_model": label_to_model,
            "model_to_label": model_to_label,
            "judge": verdict,
        })

    report = render_report(samples, providers, s.model_synth if judge else None)
    out.write_text(report)
    click.echo(f"\nReport written to {out}", err=True)


if __name__ == "__main__":
    main()
