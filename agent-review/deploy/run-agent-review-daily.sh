#!/usr/bin/env bash
# Daily agent-review cron wrapper.
#
# Runs agent-review against yesterday's agent sessions, then commits + pushes
# any resulting markdown changes in the vault. Mirrors the sibling wrappers
# for vault-review and memex-review.
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

VAULT="${VAULT_PATH:-$HOME/vault}"

agent-review run yesterday

cd "$VAULT"
if [[ -n "$(git status --porcelain)" ]]; then
    git add -A
    git commit -m "agent-review: daily report $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    # Rebase on any concurrent remote commit (e.g. another host's vault
    # auto-sync) before pushing, then retry once if we still race. Without
    # this, a non-fast-forward rejection leaves the vault diverged and every
    # subsequent cron push fails silently (auto-review-qgo).
    git pull --rebase --quiet
    git push || { git pull --rebase --quiet && git push; }
fi
