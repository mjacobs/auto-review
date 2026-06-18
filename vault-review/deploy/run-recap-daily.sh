#!/usr/bin/env bash
# Daily recap cron wrapper.
#
# Runs vault-review against yesterday's git delta, then commits + pushes any
# resulting markdown changes in the vault. Mirrors the side effects of the
# old vault-agent recap path, but isolated to the wrapper.
#
# Installed at ~/.local/bin/run-recap-daily on the cron host and invoked
# from the user crontab. PATH must include the directory holding the
# uv-tool-installed `vault-review` binary (commonly ~/.local/bin or
# /home/linuxbrew/.linuxbrew/bin).
#
# Required env (sourced from ~/.secrets if present):
#   VAULT_REVIEW_PG_DSN  postgresql://vault_review_job@<pg-host>:5432/<db>
#                        (password may instead come from ~/.pgpass). Records the
#                        ops.job_runs liveness row (auto-review-2vv). Dedicated
#                        var because ~/.secrets PG_DSN on the cron host belongs
#                        to the agent_review role. Mirrors the renderer wrapper
#                        fix in fac6bba.

set -euo pipefail

export PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"

# Load the PG DSN. Cron starts with a minimal environment.
[[ -f "$HOME/.secrets" ]] && source "$HOME/.secrets"

: "${VAULT_REVIEW_PG_DSN:?VAULT_REVIEW_PG_DSN must be set (provision ~/.secrets on this host)}"

VAULT="${VAULT_PATH:-$HOME/vault}"

vault-review run yesterday

cd "$VAULT"
if [[ -n "$(git status --porcelain)" ]]; then
    git add -A
    git commit -m "vault-review: daily recap $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    # Rebase on any concurrent remote commit (e.g. another host's vault
    # auto-sync) before pushing, then retry once if we still race. Without
    # this, a non-fast-forward rejection leaves the vault diverged and every
    # subsequent cron push fails silently (auto-review-qgo).
    git pull --rebase --quiet
    git push || { git pull --rebase --quiet && git push; }
fi
