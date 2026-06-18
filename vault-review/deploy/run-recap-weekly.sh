#!/usr/bin/env bash
# Weekly recap cron wrapper. See run-recap-daily.sh for the model.
#
# Required env (sourced from ~/.secrets if present):
#   VAULT_REVIEW_PG_DSN  postgresql://vault_review_job@<pg-host>:5432/<db>
#                        (records the ops.job_runs liveness row — auto-review-2vv;
#                        mirrors the renderer wrapper fix in fac6bba).

set -euo pipefail

export PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"

# Load the PG DSN. Cron starts with a minimal environment.
[[ -f "$HOME/.secrets" ]] && source "$HOME/.secrets"

: "${VAULT_REVIEW_PG_DSN:?VAULT_REVIEW_PG_DSN must be set (provision ~/.secrets on this host)}"

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
