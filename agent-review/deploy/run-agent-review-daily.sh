#!/usr/bin/env bash
# Daily agent-review cron wrapper.
#
# Runs agent-review against yesterday's agent sessions in --no-vault mode:
# the daily report is persisted to the agent_review PG schema ONLY — no
# markdown, no marker, no git. The check-in renderer (run-checkin-renderer-
# daily, 00:51) reads that row and emits the agent-review section as part of
# its bracket. This is the ADR 002 split: machine data lives in Postgres,
# the renderer is the single writer of the projection (beads auto-review-hg6.6).
#
# Installed at ~/.local/bin/run-agent-review-daily on the cron host and
# invoked from the user crontab. PATH must include the directory holding
# the uv-tool-installed `agent-review` binary (commonly ~/.local/bin or
# /home/linuxbrew/.linuxbrew/bin).
#
# Required env (sourced from ~/.secrets if present):
#   PG_DSN                 — recommend dedicated `agent_review` PG user, not admin
#
# LLM backend (LLM_BACKEND, default claude_cli):
#   claude_cli (default)   — digest/synth run via `claude -p`, billed to the
#                            Claude Max subscription's programmatic quota. NO
#                            API key needed. Requires:
#                              · `claude` on PATH (CLAUDE_CLI_BIN to override).
#                              · the CLI authenticated to the subscription on
#                                this host — either an interactive `claude`
#                                login, or a long-lived token from
#                                `claude setup-token` exported as
#                                CLAUDE_CODE_OAUTH_TOKEN in ~/.secrets.
#                            agent-review pins billing to the subscription: it
#                            scrubs every off-subscription auth/routing var from
#                            the `claude` subprocess (API keys, apiKeyHelper's
#                            env form, Bedrock/Vertex switches) and passes
#                            `--setting-sources ""` so a settings.json
#                            apiKeyHelper can't divert it to a Console key.
#   api                    — legacy: anthropic SDK. Needs LLM_API_KEY (and
#                            optionally LLM_BASE_URL for a LiteLLM gateway).
# Optional env:
#   VAULT_PATH
#   TZ
#   MODEL_DIGEST / MODEL_SYNTH   — full model IDs; passed to `claude --model`
#                                  (or registered on the gateway under api).
#   PGPASSFILE

set -euo pipefail

[[ -f "$HOME/.secrets" ]] && source "$HOME/.secrets"

: "${PG_DSN:?PG_DSN must be set (provision ~/.secrets on this host)}"
# Under the default claude_cli backend no API key is needed (the subscription
# pays). Only require LLM_API_KEY when explicitly using the legacy api backend.
if [[ "${LLM_BACKEND:-claude_cli}" == "api" ]]; then
  : "${LLM_API_KEY:?LLM_API_KEY must be set when LLM_BACKEND=api}"
fi

# --no-vault: write the report row to PG, touch no files. There is therefore
# no git path here — the renderer owns the vault commit/push (AGENTS.md: only
# the renderer's wrapper commits). A crashed run persists no row and goes
# overdue under the doctor's job_runs liveness check (auto-review-hg6.8).
agent-review run yesterday --no-vault
