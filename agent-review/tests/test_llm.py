"""Tests for the LLM backend abstraction (agent_review.llm) and the backend /
api-key wiring in agent_review.config."""

from __future__ import annotations

import json
import warnings

import pytest

from agent_review import llm
from agent_review.config import Settings

# ─── settings helpers ────────────────────────────────────────────────────────


def _settings(**overrides) -> Settings:
    """Build hermetic Settings (no .env, no real key needed for claude_cli)."""
    base = dict(PG_DSN="postgresql://u@h:5432/db", LLM_BACKEND="claude_cli")
    base.update(overrides)
    return Settings(_env_file=None, **base)  # type: ignore[arg-type]


def test_api_backend_requires_key():
    with pytest.raises(ValueError, match="LLM_API_KEY is required"):
        _settings(LLM_BACKEND="api", LLM_API_KEY=None)


def test_api_backend_with_key_ok():
    s = _settings(LLM_BACKEND="api", LLM_API_KEY="sk-test")
    assert s.llm_backend == "api"
    assert s.llm_api_key is not None


def test_claude_cli_backend_needs_no_key():
    s = _settings(LLM_BACKEND="claude_cli")
    assert s.llm_backend == "claude_cli"
    assert s.llm_api_key is None
    assert s.claude_cli_bin == "claude"
    assert s.claude_cli_timeout == 300


def test_default_backend_is_claude_cli():
    # No LLM_BACKEND override and no key: still valid, defaults to subscription.
    s = Settings(_env_file=None, PG_DSN="postgresql://u@h:5432/db")  # type: ignore[arg-type]
    assert s.llm_backend == "claude_cli"


# ─── argv construction ───────────────────────────────────────────────────────

TOOL = {"name": "submit_digest", "input_schema": {"type": "object", "properties": {}}}


def test_argv_text_call_has_no_json_schema():
    s = _settings()
    argv = llm._build_cli_argv(s, model="claude-sonnet-4-6", system_prompt="SYS", tool=None)
    assert argv[0] == "claude"
    assert "-p" in argv
    assert argv[argv.index("--model") + 1] == "claude-sonnet-4-6"
    assert argv[argv.index("--system-prompt") + 1] == "SYS"
    assert argv[argv.index("--output-format") + 1] == "json"
    assert "--safe-mode" in argv
    assert "--strict-mcp-config" in argv
    # one-shot calls don't persist session transcripts to disk
    assert "--no-session-persistence" in argv
    # tools disabled (empty string follows --tools)
    assert argv[argv.index("--tools") + 1] == ""
    # no settings.json loaded — blocks a host apiKeyHelper from diverting billing
    assert argv[argv.index("--setting-sources") + 1] == ""
    assert "--json-schema" not in argv


def test_argv_structured_call_includes_schema():
    s = _settings()
    argv = llm._build_cli_argv(s, model="claude-haiku-4-5", system_prompt="SYS", tool=TOOL)
    assert "--json-schema" in argv
    schema_json = argv[argv.index("--json-schema") + 1]
    assert json.loads(schema_json) == TOOL["input_schema"]


def test_argv_respects_custom_bin_and_extra_args():
    s = _settings(CLAUDE_CLI_BIN="/opt/claude", CLAUDE_CLI_EXTRA_ARGS="--max-budget-usd 0.5")
    argv = llm._build_cli_argv(s, model="m", system_prompt="SYS", tool=None)
    assert argv[0] == "/opt/claude"
    assert argv[-2:] == ["--max-budget-usd", "0.5"]


# ─── result extraction ───────────────────────────────────────────────────────


def test_extract_result_from_event_array():
    payload = json.dumps(
        [
            {"type": "system", "subtype": "init"},
            {"type": "assistant"},
            {"type": "result", "subtype": "success", "result": "hi"},
        ]
    )
    res = llm._extract_result(payload)
    assert res["result"] == "hi"


def test_extract_result_from_single_object():
    payload = json.dumps({"type": "result", "subtype": "success", "result": "hi"})
    assert llm._extract_result(payload)["result"] == "hi"


def test_extract_result_non_json_raises():
    with pytest.raises(RuntimeError, match="non-JSON"):
        llm._extract_result("not json at all")


def test_extract_result_no_result_event_raises():
    payload = json.dumps([{"type": "system"}])
    with pytest.raises(RuntimeError, match="no result event"):
        llm._extract_result(payload)


def test_cli_usage_maps_and_coerces():
    u = llm._cli_usage(
        {"input_tokens": 10, "output_tokens": 5, "cache_read_input_tokens": None}
    )
    assert u == {
        "input_tokens": 10,
        "output_tokens": 5,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0,
    }


# ─── subscription env scrubbing ──────────────────────────────────────────────


def test_subscription_env_strips_console_auth(monkeypatch: pytest.MonkeyPatch):
    # Console / direct-API auth, apiKeyHelper env form, and Bedrock/Vertex
    # routing switches must all be stripped so only subscription OAuth remains.
    for var in (
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_BASE_URL",
        "CLAUDE_CODE_API_KEY_HELPER",
        "CLAUDE_CODE_USE_BEDROCK",
        "CLAUDE_CODE_USE_VERTEX",
        "ANTHROPIC_VERTEX_PROJECT_ID",
    ):
        monkeypatch.setenv(var, "x")
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "oauth-keep")
    monkeypatch.setenv("HOME", "/home/auto-review")
    env = llm._subscription_env()
    for var in (
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_BASE_URL",
        "CLAUDE_CODE_API_KEY_HELPER",
        "CLAUDE_CODE_USE_BEDROCK",
        "CLAUDE_CODE_USE_VERTEX",
        "ANTHROPIC_VERTEX_PROJECT_ID",
    ):
        assert var not in env
    # subscription auth + unrelated env preserved
    assert env["CLAUDE_CODE_OAUTH_TOKEN"] == "oauth-keep"
    assert env["HOME"] == "/home/auto-review"


# ─── _complete_cli happy paths via fake subprocess ───────────────────────────


class _FakeProc:
    def __init__(self, stdout="", stderr="", returncode=0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


def _result_array(**result_fields) -> str:
    base = {"type": "result", "subtype": "success", "is_error": False}
    base.update(result_fields)
    return json.dumps([{"type": "system", "subtype": "init"}, base])


def _patch_run(monkeypatch, *, expect_input=None, capture=None, proc=None):
    def fake_run(argv, **kwargs):
        if capture is not None:
            capture["argv"] = argv
            capture["kwargs"] = kwargs
        if expect_input is not None:
            assert kwargs.get("input") == expect_input
        return proc
    monkeypatch.setattr(llm.subprocess, "run", fake_run)


def test_complete_cli_structured(monkeypatch: pytest.MonkeyPatch):
    usage = {"input_tokens": 100, "output_tokens": 40, "cache_read_input_tokens": 0}
    stdout = _result_array(structured_output={"summary": "did it"}, usage=usage)
    capture: dict = {}
    _patch_run(monkeypatch, expect_input="USER", capture=capture, proc=_FakeProc(stdout=stdout))

    res = llm._complete_cli(
        _settings(CLAUDE_CLI_TIMEOUT=123),
        model="m",
        system_prompt="SYS",
        user_content="USER",
        tool=TOOL,
    )
    assert res.structured == {"summary": "did it"}
    assert res.usage["input_tokens"] == 100
    # per-call timeout is actually wired into subprocess.run (guards against an
    # unattended cron call hanging forever if it were dropped)
    assert capture["kwargs"]["timeout"] == 123
    # env was scrubbed and passed
    assert "ANTHROPIC_API_KEY" not in capture["kwargs"]["env"]


def test_complete_cli_text(monkeypatch: pytest.MonkeyPatch):
    stdout = _result_array(result="the narrative", usage={"input_tokens": 1, "output_tokens": 2})
    _patch_run(monkeypatch, proc=_FakeProc(stdout=stdout))
    res = llm._complete_cli(_settings(), model="m", system_prompt="SYS", user_content="U", tool=None)
    assert res.text == "the narrative"
    assert res.usage["output_tokens"] == 2


def test_complete_cli_nonzero_exit_raises(monkeypatch: pytest.MonkeyPatch):
    _patch_run(monkeypatch, proc=_FakeProc(stderr="boom", returncode=1))
    with pytest.raises(RuntimeError, match="exited 1"):
        llm._complete_cli(_settings(), model="m", system_prompt="S", user_content="U", tool=None)


def test_complete_cli_nonzero_exit_surfaces_stdout_error(monkeypatch: pytest.MonkeyPatch):
    # claude writes "bad model" type errors to its JSON stdout, not stderr; the
    # raised error must still carry the human message (regression: an empty-stderr
    # exit once surfaced as a bare "exited 1" with no clue).
    stdout = json.dumps(
        [{"type": "result", "subtype": "error", "is_error": True,
          "result": "Model not found: local-coder"}]
    )
    _patch_run(monkeypatch, proc=_FakeProc(stdout=stdout, stderr="", returncode=1))
    with pytest.raises(RuntimeError, match="Model not found: local-coder"):
        llm._complete_cli(_settings(), model="local-coder", system_prompt="S",
                          user_content="U", tool=None)


def test_complete_cli_is_error_raises(monkeypatch: pytest.MonkeyPatch):
    stdout = json.dumps(
        [{"type": "result", "subtype": "error_during_execution", "is_error": True, "result": "nope"}]
    )
    _patch_run(monkeypatch, proc=_FakeProc(stdout=stdout))
    with pytest.raises(RuntimeError, match="reported failure"):
        llm._complete_cli(_settings(), model="m", system_prompt="S", user_content="U", tool=None)


def test_complete_cli_missing_structured_raises(monkeypatch: pytest.MonkeyPatch):
    stdout = _result_array(result="", usage={})  # no structured_output
    _patch_run(monkeypatch, proc=_FakeProc(stdout=stdout))
    with pytest.raises(RuntimeError, match="no structured_output"):
        llm._complete_cli(_settings(), model="m", system_prompt="S", user_content="U", tool=TOOL)


def test_complete_cli_empty_text_raises(monkeypatch: pytest.MonkeyPatch):
    stdout = _result_array(result="   ", usage={})
    _patch_run(monkeypatch, proc=_FakeProc(stdout=stdout))
    with pytest.raises(RuntimeError, match="empty text"):
        llm._complete_cli(_settings(), model="m", system_prompt="S", user_content="U", tool=None)


def test_complete_cli_binary_missing_raises(monkeypatch: pytest.MonkeyPatch):
    def boom(*a, **k):
        raise FileNotFoundError()
    monkeypatch.setattr(llm.subprocess, "run", boom)
    with pytest.raises(RuntimeError, match="claude CLI not found"):
        llm._complete_cli(_settings(), model="m", system_prompt="S", user_content="U", tool=None)


def test_complete_cli_timeout_raises(monkeypatch: pytest.MonkeyPatch):
    def boom(*a, **k):
        raise llm.subprocess.TimeoutExpired(cmd="claude", timeout=300)
    monkeypatch.setattr(llm.subprocess, "run", boom)
    with pytest.raises(RuntimeError, match="timed out"):
        llm._complete_cli(_settings(), model="m", system_prompt="S", user_content="U", tool=None)


# ─── dispatch ────────────────────────────────────────────────────────────────


def test_complete_dispatches_to_cli(monkeypatch: pytest.MonkeyPatch):
    seen = {}

    def fake_cli(s, **kw):
        seen.update(kw)
        return llm.LlmResult(text="ok")

    monkeypatch.setattr(llm, "_complete_cli", fake_cli)
    out = llm.complete(
        model="m", system_prompt="S", user_content="U", settings=_settings(LLM_BACKEND="claude_cli")
    )
    assert out.text == "ok"
    assert seen["model"] == "m"


def test_complete_dispatches_to_api(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(llm, "_complete_api", lambda s, **kw: llm.LlmResult(text="api"))
    out = llm.complete(
        model="m",
        system_prompt="S",
        user_content="U",
        settings=_settings(LLM_BACKEND="api", LLM_API_KEY="sk-x"),
    )
    assert out.text == "api"


# ─── per-stage backend selection ─────────────────────────────────────────────


def test_per_stage_backend_defaults_to_global():
    s = _settings(LLM_BACKEND="claude_cli")
    assert s.digest_backend == "claude_cli"
    assert s.synth_backend == "claude_cli"


def test_per_stage_backend_override():
    # The hybrid the homelab uses: digest on the local-model gateway, synth on
    # the subscription.
    s = _settings(LLM_BACKEND="claude_cli", LLM_BACKEND_DIGEST="api", LLM_API_KEY="sk-x")
    assert s.digest_backend == "api"
    assert s.synth_backend == "claude_cli"


def test_per_stage_api_requires_key():
    with pytest.raises(ValueError, match="LLM_API_KEY is required"):
        _settings(LLM_BACKEND="claude_cli", LLM_BACKEND_DIGEST="api", LLM_API_KEY=None)


def test_complete_honors_explicit_backend(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(llm, "_complete_api", lambda s, **kw: llm.LlmResult(text="api"))
    monkeypatch.setattr(llm, "_complete_cli", lambda s, **kw: llm.LlmResult(text="cli"))
    s = _settings(LLM_BACKEND="claude_cli", LLM_BACKEND_DIGEST="api", LLM_API_KEY="sk-x")
    # explicit backend arg overrides settings.llm_backend (this is how digest/
    # synth route to their own per-stage backend)
    assert (
        llm.complete(model="m", system_prompt="S", user_content="U",
                     settings=s, backend=s.digest_backend).text == "api"
    )
    assert (
        llm.complete(model="m", system_prompt="S", user_content="U",
                     settings=s, backend=s.synth_backend).text == "cli"
    )


# ─── backend↔model coherence guard (2026-06 digest-404 incident) ─────────────


def test_claude_cli_backend_rejects_non_claude_digest_model():
    # The exact misconfig that 404'd for ~3 days: MODEL_DIGEST=local-coder (a
    # gateway-only id) shelled to `claude -p --model local-coder`.
    with pytest.raises(ValueError, match=r"MODEL_DIGEST='local-coder' is not a Claude"):
        _settings(LLM_BACKEND="claude_cli", MODEL_DIGEST="local-coder")


def test_claude_cli_backend_rejects_non_claude_synth_model():
    with pytest.raises(ValueError, match=r"MODEL_SYNTH='qwen-coder' is not a Claude"):
        _settings(LLM_BACKEND="claude_cli", MODEL_SYNTH="qwen-coder")


def test_claude_cli_backend_accepts_claude_models():
    s = _settings(
        LLM_BACKEND="claude_cli",
        MODEL_DIGEST="claude-haiku-4-5-20251001",
        MODEL_SYNTH="claude-sonnet-4-6",
    )
    assert s.model_digest == "claude-haiku-4-5-20251001"
    assert s.model_synth == "claude-sonnet-4-6"


def test_claude_model_token_match_is_case_insensitive():
    # Any of the family tokens, in any case, marks a model as Claude-routable.
    for model in ("Claude-3", "HAIKU-x", "my-Opus", "sonnet-latest"):
        s = _settings(LLM_BACKEND="claude_cli", MODEL_DIGEST=model, MODEL_SYNTH=model)
        assert s.digest_backend == "claude_cli"


def test_non_claude_model_is_fine_under_api_backend():
    # A gateway/local model id is legitimate when its stage runs on the api
    # backend — the guard must only fire for the claude_cli backend.
    s = _settings(
        LLM_BACKEND="claude_cli",
        LLM_BACKEND_DIGEST="api",
        MODEL_DIGEST="local-coder",
        LLM_API_KEY="sk-x",
    )
    assert s.digest_backend == "api"
    assert s.model_digest == "local-coder"


def test_warns_on_dead_base_url_when_api_backend_unused():
    with pytest.warns(UserWarning, match=r"LLM_BASE_URL.*no stage uses the api backend"):
        _settings(LLM_BACKEND="claude_cli", LLM_BASE_URL="https://gw.example")


def test_warns_on_dead_api_key_when_api_backend_unused():
    with pytest.warns(UserWarning, match=r"LLM_API_KEY.*no stage uses the api backend"):
        _settings(LLM_BACKEND="claude_cli", LLM_API_KEY="sk-unused")


def test_no_dead_knob_warning_when_api_backend_in_use():
    # A stage genuinely on the api backend uses LLM_API_KEY/LLM_BASE_URL, so the
    # dead-weight warning must NOT fire (treat any UserWarning as an error).
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        s = _settings(
            LLM_BACKEND="claude_cli",
            LLM_BACKEND_DIGEST="api",
            LLM_API_KEY="sk-x",
            LLM_BASE_URL="https://gw.example",
            MODEL_DIGEST="local-coder",
        )
        assert s.digest_backend == "api"
