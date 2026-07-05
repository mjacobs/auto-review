"""Process-wide config, populated from env / .env."""

from __future__ import annotations

import socket
import warnings
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Substrings (case-insensitive) that mark a model id as Claude-family, i.e.
# routable by `claude -p --model <id>`. A gateway/api-only id like "local-coder"
# has none of these and 404s under the claude_cli backend — the misconfig that
# broke the digest stage for ~3 days in 2026-06 (see _validate_backend_model_coherence).
_CLAUDE_MODEL_TOKENS = ("claude", "haiku", "sonnet", "opus")


def _looks_like_claude_model(model: str) -> bool:
    """True when ``model`` names a Claude-family model the ``claude`` CLI accepts."""
    lowered = model.lower()
    return any(token in lowered for token in _CLAUDE_MODEL_TOKENS)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    pg_dsn: SecretStr = Field(..., alias="PG_DSN")

    # LLM backend for the digest (Stage 2) and synth (Stage 3) calls:
    #   "claude_cli" — shell out to `claude -p` (billed to the Claude Max
    #                  subscription's programmatic quota; no API key needed).
    #   "api"        — the anthropic SDK over LLM_API_KEY/LLM_BASE_URL (direct
    #                  Anthropic, or a LiteLLM gateway fronting a local model).
    # Default is claude_cli: the Console API account is unfunded, so the
    # subscription is the only first-party path. See llm.py.
    llm_backend: Literal["api", "claude_cli"] = Field("claude_cli", alias="LLM_BACKEND")

    # Per-stage backend overrides. Each defaults to llm_backend when unset, so a
    # mixed setup is possible — e.g. digest on a local model via the gateway
    # (LLM_BACKEND_DIGEST=api, MODEL_DIGEST=local-coder) while synth uses the
    # subscription (LLM_BACKEND_SYNTH=claude_cli). Resolved via the
    # digest_backend / synth_backend properties below.
    backend_digest: Literal["api", "claude_cli"] | None = Field(None, alias="LLM_BACKEND_DIGEST")
    backend_synth: Literal["api", "claude_cli"] | None = Field(None, alias="LLM_BACKEND_SYNTH")

    # Required only when an effective stage backend is "api" (enforced below).
    llm_api_key: SecretStr | None = Field(None, alias="LLM_API_KEY")
    llm_base_url: str | None = Field(None, alias="LLM_BASE_URL")

    # claude_cli backend knobs.
    claude_cli_bin: str = Field("claude", alias="CLAUDE_CLI_BIN")
    claude_cli_timeout: int = Field(300, alias="CLAUDE_CLI_TIMEOUT")
    # Extra flags appended to every `claude -p` invocation (shlex-split). Escape
    # hatch for e.g. `--max-budget-usd 0.50`. Normally empty.
    claude_cli_extra_args: str = Field("", alias="CLAUDE_CLI_EXTRA_ARGS")

    tz_name: str = Field("America/Los_Angeles", alias="TZ")
    model_digest: str = Field("claude-haiku-4-5-20251001", alias="MODEL_DIGEST")
    model_synth: str = Field("claude-sonnet-4-6", alias="MODEL_SYNTH")
    # Schema name for the upstream read-only database (default: agentsview).
    pg_schema: str = Field("agentsview", alias="AGENT_REVIEW_PG_SCHEMA")

    # ops.job_runs identity (auto-review-hg6.8). job_name must match a
    # pre-registered ops.jobs row (FK; seeded in db/migrations/0007). job_host
    # defaults to the machine hostname, matching the sibling PG writers.
    job_name: str = Field("agent-review", alias="AGENT_REVIEW_JOB_NAME")
    job_host: str = Field("", alias="AGENT_REVIEW_HOST")

    @property
    def digest_backend(self) -> str:
        """Effective backend for Stage 2 (per-stage override → global default)."""
        return self.backend_digest or self.llm_backend

    @property
    def synth_backend(self) -> str:
        """Effective backend for Stage 3 (per-stage override → global default)."""
        return self.backend_synth or self.llm_backend

    @model_validator(mode="after")
    def _require_api_key_for_api_backend(self) -> Settings:
        if "api" in (self.digest_backend, self.synth_backend) and self.llm_api_key is None:
            raise ValueError(
                "LLM_API_KEY is required when a stage uses the api backend "
                "(LLM_BACKEND / LLM_BACKEND_DIGEST / LLM_BACKEND_SYNTH = api). Set a "
                "key, or use claude_cli to bill the Claude Max subscription instead."
            )
        return self

    @model_validator(mode="after")
    def _validate_backend_model_coherence(self) -> Settings:
        """Fail fast on a claude_cli↔non-Claude-model mismatch; warn on dead
        api-only knobs.

        Root cause of the 2026-06 digest outage: a package default flip of
        LLM_BACKEND (api→claude_cli) meant the prod config's
        MODEL_DIGEST=local-coder (a gateway-only id) was suddenly shelled to
        `claude -p --model local-coder`, which 404s. Nothing validated the
        backend↔model pairing, so it surfaced only at runtime — masked by
        tenacity as an opaque RetryError — and stayed broken for ~3 days. This
        turns that class of misconfig into a clear startup error.
        """
        # Fatal: a stage on claude_cli whose model isn't Claude-recognizable
        # would 404 on every call. Name the stage, model, and backend.
        for stage, backend, model in (
            ("digest", self.digest_backend, self.model_digest),
            ("synth", self.synth_backend, self.model_synth),
        ):
            if backend == "claude_cli" and not _looks_like_claude_model(model):
                raise ValueError(
                    f"{stage} stage uses the claude_cli backend but "
                    f"MODEL_{stage.upper()}={model!r} is not a Claude-recognizable "
                    f"model (no 'claude'/'haiku'/'sonnet'/'opus' token). "
                    f"`claude -p --model {model}` would 404. Set a Claude model id, "
                    f"or set LLM_BACKEND_{stage.upper()}=api to route this stage to a "
                    f"gateway/local model."
                )

        # Nudge (not fatal): api-only knobs are set while the api backend is
        # entirely unused (both stages on claude_cli), so they do nothing. A
        # non-Claude MODEL_* under claude_cli already raised above, so the only
        # remaining dead weight here is the api credential/endpoint knobs.
        if self.digest_backend == "claude_cli" and self.synth_backend == "claude_cli":
            unused = []
            if self.llm_base_url is not None:
                unused.append("LLM_BASE_URL")
            if self.llm_api_key is not None:
                unused.append("LLM_API_KEY")
            if unused:
                warnings.warn(
                    f"{', '.join(unused)} set but no stage uses the api backend "
                    f"(both digest and synth run on claude_cli); these knobs are "
                    f"ignored. Remove them, or set LLM_BACKEND[_DIGEST|_SYNTH]=api to "
                    f"use them.",
                    stacklevel=2,
                )
        return self

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.tz_name)

    @property
    def host(self) -> str:
        return self.job_host or socket.gethostname()


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()  # type: ignore[call-arg]
    return _settings
