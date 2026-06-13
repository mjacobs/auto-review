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
#   31 0 * * *  run-auto-review-doctor  >> ~/.local/state/auto-review/cron.log 2>&1
# 00:31 PT runs last in the just-after-midnight chain (vault 00:01, memex 00:11,
# agent 00:21) so the doctor sees the night's daily run results. The chain was
# moved from the old 20:01-22:01 PT slot so each day's recap materializes right
# after the day closes instead of ~21h later (auto-review-d4c follow-up).

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
