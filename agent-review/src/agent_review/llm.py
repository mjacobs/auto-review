"""LLM backend abstraction for the digest (Stage 2) and synth (Stage 3) calls.

Two backends, selected by ``Settings.llm_backend``:

- ``api`` — the original path: the ``anthropic`` SDK hitting ``LLM_BASE_URL``
  (Anthropic direct or a LiteLLM gateway) with ``LLM_API_KEY``.
- ``claude_cli`` — shell out to ``claude -p`` so calls are billed against the
  **Claude Max subscription**'s programmatic quota instead of a (now unfunded)
  Console API key. Verified against claude 2.1.179.

Both expose a single :func:`complete` that returns an :class:`LlmResult`
(``text`` and/or ``structured`` plus a normalized ``usage`` dict), so
``digest.py`` (structured, forced schema) and ``synth.py`` (free text) share one
call path and one usage shape — the same four keys ``estimate_cost`` expects.

### claude_cli mechanics

``claude -p`` is invoked with the user payload on **stdin** and:

- ``--model <id>``        — full model IDs (``claude-haiku-4-5-…``) are honored.
- ``--system-prompt``     — *replaces* Claude Code's default prompt with ours.
- ``--output-format json``— stdout is a JSON array of stream events; the final
                            ``type=="result"`` element carries ``result`` (text),
                            ``structured_output`` (when ``--json-schema`` is set),
                            and ``usage``.
- ``--json-schema``       — forces schema-valid structured output (the digest's
                            pydantic schema, ``$defs``/``$ref`` and all). This is
                            the CLI equivalent of the API's forced ``tool_choice``.
- ``--safe-mode``         — disables CLAUDE.md / hooks / MCP / skills / plugins,
                            but keeps subscription auth + model selection. Keeps
                            the call cheap (no stray tool schemas billed) and
                            deterministic.
- ``--tools ""``          — disables all built-in tools. The call is a pure
                            completion; it can never run Bash/Edit/etc. on the
                            host. (Safety: agent-review runs unattended on a
                            shared cron host.)
- ``--strict-mcp-config`` — belt-and-suspenders: zero MCP servers even if some
                            are configured for the user.

To guarantee the call bills the **subscription** and not some other account, two
things lock auth down (a shared host may carry config for unrelated tooling):

- the subprocess env is scrubbed of every Anthropic/Console auth + provider-
  routing var (``_API_AUTH_ENV``) — direct API keys, ``apiKeyHelper``'s env
  form, and the Bedrock/Vertex switches that would divert inference to a cloud
  account; and
- ``--setting-sources ""`` stops ``claude`` from loading any user/project
  ``settings.json`` — whose ``apiKeyHelper`` would otherwise return a Console
  key that *outranks* subscription OAuth (``--safe-mode`` keeps auth, so it does
  not close this on its own).

What's left is subscription auth only: keychain OAuth or ``CLAUDE_CODE_OAUTH_TOKEN``.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
from dataclasses import dataclass, field
from typing import Any

from anthropic import Anthropic

from .config import Settings, get_settings

# Env that would route `claude -p` off the Max subscription (to a Console API
# key or a Bedrock/Vertex cloud account). Stripped from the subprocess env so
# auth can only resolve to the subscription.
_API_AUTH_ENV = (
    # Anthropic direct-API / Console auth + endpoint overrides
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_API_URL",
    "ANTHROPIC_CUSTOM_HEADERS",
    # apiKeyHelper's env form — returns a key that outranks subscription OAuth
    "CLAUDE_CODE_API_KEY_HELPER",
    # Bedrock / Vertex provider routing — would bill a cloud account, not the sub
    "CLAUDE_CODE_USE_BEDROCK",
    "CLAUDE_CODE_USE_VERTEX",
    "CLAUDE_CODE_SKIP_BEDROCK_AUTH",
    "CLAUDE_CODE_SKIP_VERTEX_AUTH",
    "ANTHROPIC_VERTEX_PROJECT_ID",
)


@dataclass
class LlmResult:
    """Backend-agnostic result. ``structured`` is set for tool/schema calls
    (digest); ``text`` for free-text calls (synth). ``usage`` always carries the
    four token keys ``estimate_cost`` reads."""

    text: str | None = None
    structured: dict[str, Any] | None = None
    usage: dict[str, int] = field(default_factory=dict)


def complete(
    *,
    model: str,
    system_prompt: str,
    user_content: str,
    max_tokens: int = 4096,
    tool: dict[str, Any] | None = None,
    settings: Settings | None = None,
) -> LlmResult:
    """Run one completion against the configured backend.

    When ``tool`` is given (a ``{"name", "input_schema", ...}`` dict), the call
    is forced to produce structured output matching ``tool["input_schema"]`` and
    the result is returned in ``LlmResult.structured``; otherwise free text is
    returned in ``LlmResult.text``. ``max_tokens`` applies to the API backend
    only (the CLI uses the model's default ceiling).
    """
    s = settings or get_settings()
    if s.llm_backend == "claude_cli":
        return _complete_cli(
            s, model=model, system_prompt=system_prompt, user_content=user_content, tool=tool
        )
    return _complete_api(
        s,
        model=model,
        system_prompt=system_prompt,
        user_content=user_content,
        max_tokens=max_tokens,
        tool=tool,
    )


# ─── api backend (anthropic SDK) ─────────────────────────────────────────────


def _complete_api(
    s: Settings,
    *,
    model: str,
    system_prompt: str,
    user_content: str,
    max_tokens: int,
    tool: dict[str, Any] | None,
) -> LlmResult:
    client = Anthropic(
        api_key=s.llm_api_key.get_secret_value() if s.llm_api_key else None,
        base_url=s.llm_base_url,
    )
    kwargs: dict[str, Any] = dict(
        model=model,
        max_tokens=max_tokens,
        system=[
            {
                "type": "text",
                "text": system_prompt,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[{"role": "user", "content": user_content}],
    )
    if tool is not None:
        kwargs["tools"] = [tool]
        kwargs["tool_choice"] = {"type": "tool", "name": tool["name"]}

    response = client.messages.create(**kwargs)
    usage = _api_usage(response.usage)

    if tool is not None:
        block = next(
            (b for b in response.content if getattr(b, "type", None) == "tool_use"),
            None,
        )
        if block is None:
            stop_reason = getattr(response, "stop_reason", "unknown")
            raise RuntimeError(
                f"No tool_use block in response (stop_reason={stop_reason}, model={model})"
            )
        return LlmResult(structured=dict(block.input), usage=usage)

    block = next(
        (b for b in response.content if getattr(b, "type", None) == "text"),
        None,
    )
    if block is None:
        raise RuntimeError(f"No text block in response (model={model})")
    return LlmResult(text=block.text.strip(), usage=usage)


def _api_usage(u: Any) -> dict[str, int]:
    return {
        "input_tokens": u.input_tokens,
        "output_tokens": u.output_tokens,
        "cache_read_input_tokens": getattr(u, "cache_read_input_tokens", 0) or 0,
        "cache_creation_input_tokens": getattr(u, "cache_creation_input_tokens", 0) or 0,
    }


# ─── claude_cli backend (`claude -p`) ────────────────────────────────────────


def _build_cli_argv(
    s: Settings, *, model: str, system_prompt: str, tool: dict[str, Any] | None
) -> list[str]:
    argv = [
        s.claude_cli_bin,
        "-p",
        "--model",
        model,
        "--system-prompt",
        system_prompt,
        "--output-format",
        "json",
        "--safe-mode",
        "--strict-mcp-config",
        # One-shot calls are never resumed — don't write session transcripts to
        # disk (keeps ~/.claude from growing on the cron host's small volume).
        "--no-session-persistence",
        # Load no user/project/local settings.json — its `apiKeyHelper` would
        # return a Console key that outranks subscription OAuth (safe-mode keeps
        # auth, so it can't block this). Empty list = no sources.
        "--setting-sources",
        "",
        "--tools",
        "",
    ]
    if tool is not None:
        argv += ["--json-schema", json.dumps(tool["input_schema"])]
    if s.claude_cli_extra_args:
        argv += shlex.split(s.claude_cli_extra_args)
    return argv


def _complete_cli(
    s: Settings,
    *,
    model: str,
    system_prompt: str,
    user_content: str,
    tool: dict[str, Any] | None,
) -> LlmResult:
    argv = _build_cli_argv(s, model=model, system_prompt=system_prompt, tool=tool)
    try:
        proc = subprocess.run(
            argv,
            input=user_content,
            capture_output=True,
            text=True,
            timeout=s.claude_cli_timeout,
            env=_subscription_env(),
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            f"claude CLI not found ({s.claude_cli_bin!r}); set CLAUDE_CLI_BIN or "
            f"install Claude Code on this host"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"claude -p timed out after {s.claude_cli_timeout}s (model={model})"
        ) from exc

    if proc.returncode != 0:
        raise RuntimeError(
            f"claude -p exited {proc.returncode} (model={model}): {_tail(proc.stderr)}"
        )

    result = _extract_result(proc.stdout, stderr=proc.stderr)
    if result.get("is_error") or result.get("subtype") != "success":
        detail = _tail(str(result.get("result") or "") or proc.stderr)
        raise RuntimeError(
            f"claude -p reported failure (subtype={result.get('subtype')}, "
            f"model={model}): {detail}"
        )

    usage = _cli_usage(result.get("usage") or {})

    if tool is not None:
        structured = result.get("structured_output")
        if not isinstance(structured, dict):
            raise RuntimeError(
                f"claude -p returned no structured_output (model={model}); "
                f"got {type(structured).__name__}"
            )
        return LlmResult(structured=structured, usage=usage)

    text = (result.get("result") or "").strip()
    if not text:
        raise RuntimeError(f"claude -p returned empty text (model={model})")
    return LlmResult(text=text, usage=usage)


def _subscription_env() -> dict[str, str]:
    """A copy of the process env with Anthropic Console-auth vars removed, so
    ``claude`` falls back to subscription auth (keychain OAuth or
    ``CLAUDE_CODE_OAUTH_TOKEN``)."""
    env = dict(os.environ)
    for key in _API_AUTH_ENV:
        env.pop(key, None)
    return env


def _extract_result(stdout: str, *, stderr: str = "") -> dict[str, Any]:
    """Pull the final ``type=="result"`` element out of ``claude -p``'s JSON.

    ``--output-format json`` emits a JSON array of stream events; older/other
    shapes may emit a single result object. Tolerate both."""
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"claude -p produced non-JSON output: {_tail(stdout) or _tail(stderr)}"
        ) from exc

    if isinstance(data, list):
        results = [m for m in data if isinstance(m, dict) and m.get("type") == "result"]
        if not results:
            raise RuntimeError("claude -p output had no result event")
        return results[-1]
    if isinstance(data, dict):
        return data
    raise RuntimeError(f"claude -p produced unexpected output shape: {type(data).__name__}")


def _cli_usage(u: dict[str, Any]) -> dict[str, int]:
    return {
        "input_tokens": int(u.get("input_tokens") or 0),
        "output_tokens": int(u.get("output_tokens") or 0),
        "cache_read_input_tokens": int(u.get("cache_read_input_tokens") or 0),
        "cache_creation_input_tokens": int(u.get("cache_creation_input_tokens") or 0),
    }


def _tail(text: str | None, n: int = 500) -> str:
    text = (text or "").strip()
    return text[-n:]
