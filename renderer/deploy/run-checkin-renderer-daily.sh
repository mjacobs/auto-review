#!/usr/bin/env bash
# Daily check-in renderer cron wrapper.
#
# Renders yesterday's check-in bracket from Postgres rows, then commits +
# pushes any resulting markdown change in the vault. The wrapper owns the git
# path (AGENTS.md: cron wrappers own their own push); the renderer itself
# records its ops.job_runs row.
#
# Installed at ~/.local/bin/run-checkin-renderer-daily on the cron host and
# invoked from the user crontab (19 0 * * * — after agent-review (00:08) has
# landed its PG row and the 00:05 hourly memex-sync so late captures are in the
# mirror; see docs/schedules.md).
# PATH must include the directory holding the uv-tool-installed
# `checkin-renderer` binary (commonly ~/.local/bin).
#
# Required env (sourced from ~/.secrets if present):
#   CHECKIN_RENDERER_PG_DSN  postgresql://checkin_renderer@<pg-host>:5432/<db>
#                            (password may instead come from ~/.pgpass).
#                            Dedicated var because ~/.secrets PG_DSN on the
#                            cron host belongs to the agent_review role.

set -euo pipefail

export PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"

# Load the PG DSN. Cron starts with a minimal environment.
[[ -f "$HOME/.secrets" ]] && source "$HOME/.secrets"

: "${CHECKIN_RENDERER_PG_DSN:?CHECKIN_RENDERER_PG_DSN must be set (provision ~/.secrets on this host)}"

VAULT="${VAULT_PATH:-$HOME/vault}"

checkin-renderer run yesterday

cd "$VAULT"
if [[ -n "$(git status --porcelain)" ]]; then
    git add -A
    git commit -m "checkin-renderer: daily render $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    # Rebase on any concurrent remote commit (e.g. another host's vault
    # auto-sync) before pushing, then retry once if we still race. Without
    # this, a non-fast-forward rejection leaves the vault diverged and every
    # subsequent cron push fails silently (auto-review-qgo).
    git pull --rebase --quiet
    git push || { git pull --rebase --quiet && git push; }
fi
