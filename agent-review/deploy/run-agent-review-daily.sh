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
#   LLM_API_KEY            — key for the LLM endpoint. When LLM_BASE_URL points
#                            at a LiteLLM gateway, this is a gateway virtual
#                            key; otherwise a direct provider key.
# Optional env:
#   LLM_BASE_URL           — override the LLM SDK base URL. Point at an
#                            internal LiteLLM gateway (e.g.
#                            https://llm.example.internal) so this host only
#                            needs a scoped gateway virtual key.
#   VAULT_PATH
#   TZ
#   MODEL_DIGEST           — must be registered on the gateway when LLM_BASE_URL is set
#   MODEL_SYNTH            — same as MODEL_DIGEST
#   PGPASSFILE

set -euo pipefail

[[ -f "$HOME/.secrets" ]] && source "$HOME/.secrets"

: "${PG_DSN:?PG_DSN must be set (provision ~/.secrets on this host)}"
: "${LLM_API_KEY:?LLM_API_KEY must be set}"

# --no-vault: write the report row to PG, touch no files. There is therefore
# no git path here — the renderer owns the vault commit/push (AGENTS.md: only
# the renderer's wrapper commits). A crashed run persists no row and goes
# overdue under the doctor's job_runs liveness check (auto-review-hg6.8).
agent-review run yesterday --no-vault
