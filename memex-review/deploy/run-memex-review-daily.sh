#!/usr/bin/env bash
# Daily memex-review cron wrapper.
#
# Runs memex-review against yesterday's captures, then commits + pushes any
# resulting markdown changes in the vault. Sibling of vault-review's
# run-recap-daily; pattern lifted from there.
#
# Installed at ~/.local/bin/run-memex-review-daily on the cron host and
# invoked from the user crontab. PATH must include the directory holding
# the uv-tool-installed `memex-review` binary (commonly ~/.local/bin or
# /home/linuxbrew/.linuxbrew/bin).
#
# Required env (sourced from ~/.secrets if present):
#   MEMEX_URL
#   MEMEX_CLIENT_ID
#   MEMEX_CLIENT_SECRET

set -euo pipefail

# Load CF Access service-token creds + worker URL.
[[ -f "$HOME/.secrets" ]] && source "$HOME/.secrets"

: "${MEMEX_URL:?MEMEX_URL must be set (provision ~/.secrets on this host)}"
: "${MEMEX_CLIENT_ID:?MEMEX_CLIENT_ID must be set}"
: "${MEMEX_CLIENT_SECRET:?MEMEX_CLIENT_SECRET must be set}"

VAULT="${VAULT_PATH:-$HOME/vault}"

memex-review run yesterday

cd "$VAULT"
if [[ -n "$(git status --porcelain)" ]]; then
    git add -A
    git commit -m "memex-review: daily inbox $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    git push
fi
