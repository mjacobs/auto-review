#!/usr/bin/env bash
# Weekly recap cron wrapper. See run-recap-daily.sh for the model.

set -euo pipefail

VAULT="${VAULT_PATH:-$HOME/vault}"

vault-review run-weekly last-week

cd "$VAULT"
if [[ -n "$(git status --porcelain)" ]]; then
    git add -A
    git commit -m "vault-review: weekly recap $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    # Rebase on any concurrent remote commit (e.g. another host's vault
    # auto-sync) before pushing, then retry once if we still race. Without
    # this, a non-fast-forward rejection leaves the vault diverged and every
    # subsequent cron push fails silently (auto-review-qgo).
    git pull --rebase --quiet
    git push || { git pull --rebase --quiet && git push; }
fi
