#!/usr/bin/env bash
# Daily auto-review doctor cron wrapper.
#
# Runs the doctor script against today's cron.log + yesterday's check-in,
# writes a health section into today's check-in note, then commits + pushes
# any resulting markdown change in the vault.
#
# Installed on openclaw at ~/.local/bin/run-auto-review-doctor and invoked
# from the user crontab. The `auto-review-doctor` python script (sibling
# file in this dir, deployed to ~/.local/bin/) must also be on PATH.
#
# Cron line (gated on user confirmation per AGENTS.md):
#   1 22 * * *  run-auto-review-doctor  >> ~/.local/state/vault-agent/cron.log 2>&1
# 22:01 PT is ≥30 min after memex-review's 20:31 fire so the doctor sees
# today's daily run results.

set -euo pipefail

VAULT="${VAULT_PATH:-$HOME/vault}"

auto-review-doctor

cd "$VAULT"
if [[ -n "$(git status --porcelain)" ]]; then
    git add -A
    git commit -m "auto-review doctor: daily health $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    git push
fi
