#!/usr/bin/env bash
# Daily agent-review cron wrapper.
#
# Runs agent-review against yesterday's agent sessions, then commits + pushes
# any resulting markdown changes in the vault. Mirrors the sibling wrappers
# for vault-review and memex-review.
#
# Installed on openclaw at ~/.local/bin/run-agent-review-daily and invoked
# from the user crontab. PATH must include /home/linuxbrew/.linuxbrew/bin
# so the uv-tool-installed `agent-review` is reachable.
#
# Required env (sourced from ~/.secrets if present):
#   PG_DSN
#   ANTHROPIC_API_KEY
# Optional env:
#   VAULT_PATH
#   TZ
#   MODEL_DIGEST
#   MODEL_SYNTH
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
