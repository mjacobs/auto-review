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
#   ANTHROPIC_API_KEY      — when ANTHROPIC_BASE_URL is set, this is a LiteLLM
#                            virtual key; otherwise a real Anthropic key.
# Optional env:
#   ANTHROPIC_BASE_URL     — e.g. http://PORTAINER_HOST:4000 to route through
#                            the homelab LiteLLM gateway. Recommended for
#                            unattended cron: keeps the shared Anthropic key
#                            off the cron host.
#   VAULT_PATH
#   TZ
#   MODEL_DIGEST           — must be registered on the gateway when ANTHROPIC_BASE_URL is set
#   MODEL_SYNTH            — same as MODEL_DIGEST
#   PGPASSFILE

set -euo pipefail

[[ -f "$HOME/.secrets" ]] && source "$HOME/.secrets"

: "${PG_DSN:?PG_DSN must be set (provision ~/.secrets on this host)}"
: "${ANTHROPIC_API_KEY:?ANTHROPIC_API_KEY must be set}"

VAULT="${VAULT_PATH:-$HOME/vault}"

agent-review run yesterday

cd "$VAULT"
if [[ -n "$(git status --porcelain)" ]]; then
    git add -A
    git commit -m "agent-review: daily report $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    git push
fi
