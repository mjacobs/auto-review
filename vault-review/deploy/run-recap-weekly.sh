#!/usr/bin/env bash
# Weekly recap cron wrapper. See run-recap-daily.sh for the model.

set -euo pipefail

VAULT="${VAULT_PATH:-$HOME/vault}"

vault-review run-weekly last-week

cd "$VAULT"
if [[ -n "$(git status --porcelain)" ]]; then
    git add -A
    git commit -m "vault-review: weekly recap $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    git push
fi
