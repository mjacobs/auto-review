#!/usr/bin/env bash
# Daily auto-review doctor cron wrapper.
#
# Runs the doctor script against today's cron.log + yesterday's check-in,
# writes a health section into today's check-in note, then commits + pushes
# any resulting markdown change in the vault.
#
# Installed at ~/.local/bin/run-auto-review-doctor on the cron host and
# invoked from the user crontab. The `auto-review-doctor` python script
# (sibling file in this dir, deployed to ~/.local/bin/) must also be on PATH.
#
# Cron line (gated on user confirmation per AGENTS.md):
#   22 0 * * *  run-auto-review-doctor  >> ~/.local/state/auto-review/cron.log 2>&1
# 00:22 PT runs LAST in the tightened just-after-midnight cluster (vault-review
# 00:01, memex 00:05, agent-review + weekly[Mon] 00:08, renderer 00:19) so the
# doctor sees the night's run results — including the renderer, which the old
# 00:31 slot ran *before*. See docs/schedules.md.

set -euo pipefail

# Source ~/.secrets for AUTO_REVIEW_DOCTOR_PG_DSN (ops.job_runs liveness,
# auto-review-hg6.8). The cron-invoked wrapper gets no interactive profile, so
# without this the DSN is never seen (the renderer wrapper needed the same fix,
# fac6bba). The DSN is OPTIONAL — absent it, the doctor degrades to log/marker
# liveness and shows the PG jobs as "unknown" — so there is NO hard `:?` guard.
[[ -f "$HOME/.secrets" ]] && source "$HOME/.secrets"

VAULT="${VAULT_PATH:-$HOME/vault}"

auto-review-doctor

cd "$VAULT"
if [[ -n "$(git status --porcelain)" ]]; then
    git add -A
    git commit -m "auto-review doctor: daily health $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    # Rebase on any concurrent remote commit (e.g. another host's vault
    # auto-sync) before pushing, then retry once if we still race. Without
    # this, a non-fast-forward rejection leaves the vault diverged and every
    # subsequent cron push fails silently (auto-review-qgo).
    git pull --rebase --quiet
    git push || { git pull --rebase --quiet && git push; }
fi
