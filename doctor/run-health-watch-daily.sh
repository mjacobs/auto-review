#!/usr/bin/env bash
# Daily auto-review health-watch cron wrapper.
#
# Runs the LLM-driven health-watch against today's check-in, yesterday's
# check-in, and the cron.log tail; writes a `## health-watch` section
# into today's check-in; commits + pushes the vault.
#
# Installed at ~/.local/bin/run-health-watch-daily on the cron host.
# Companion files:
#   ~/.local/bin/health-watch                          (the python script)
#   ~/.config/auto-review/HEALTH-WATCH-CONTEXT.md      (operator playbook,
#                                                       not committed —
#                                                       see HEALTH-WATCH-CONTEXT.example.md)
#
# Required env (sourced from ~/.secrets):
#   ANTHROPIC_API_KEY      — API key sent as x-api-key. When ANTHROPIC_BASE_URL
#                            is set this is a gateway virtual key; otherwise a
#                            real Anthropic key.
# Optional env:
#   ANTHROPIC_BASE_URL     — override the SDK base URL, e.g. an internal
#                            LiteLLM gateway. Recommended for unattended cron
#                            so the cron host carries a scoped virtual key
#                            instead of the shared Anthropic key.
#   VAULT_PATH             — defaults to ~/vault
#   HEALTH_WATCH_MODEL     — defaults to claude-sonnet-4-6
#   HEALTH_WATCH_CONTEXT   — override the playbook path
#
# Cron line (08:00 PT — after the 22:01 PT doctor has settled overnight):
#   0 8 * * *  run-health-watch-daily  >> ~/.local/state/vault-agent/cron.log 2>&1
#
# Exit codes:
#   0 — GREEN, section written, vault pushed.
#   2 — NON-GREEN, section still written + pushed; cron MAILTO (if set)
#       gets notified. Findings are also in the written section.
#   other — hard failure (missing env, LLM error, malformed response).

set -uo pipefail

[[ -f "$HOME/.secrets" ]] && source "$HOME/.secrets"

: "${ANTHROPIC_API_KEY:?ANTHROPIC_API_KEY must be set (LiteLLM virtual key)}"

VAULT="${VAULT_PATH:-$HOME/vault}"

set +e
health-watch
rc=$?
set -e

if [[ $rc -ne 0 && $rc -ne 2 ]]; then
    echo "health-watch exited with $rc (hard failure)" >&2
    exit "$rc"
fi

cd "$VAULT"
if [[ -n "$(git status --porcelain)" ]]; then
    git add -A
    git commit -m "auto-review health-watch: daily $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    git push
fi

exit "$rc"
