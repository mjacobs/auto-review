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

set -euo pipefail

VAULT="${VAULT_PATH:-$HOME/vault}"

vault-review run yesterday

cd "$VAULT"
if [[ -n "$(git status --porcelain)" ]]; then
    git add -A
    git commit -m "vault-review: daily recap $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    git push
fi
