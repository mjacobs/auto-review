#!/usr/bin/env bash
# memex-triage delivery wrapper — target of the desktop systemd --user timer.
#
# Runs `memex-triage sync` (which writes inbox/memex.md ONLY when there are new
# captures), then commits + pushes JUST that file. Two deliberate choices for a
# */5 job on a desktop you're actively editing in:
#
#   * Commit only the inbox file, not `git add -A`, so this never sweeps up your
#     in-progress Obsidian edits to other notes.
#   * `git pull --rebase --autostash` so the rebase coexists with whatever else
#     is dirty in the vault and with the LXC runner's daily commits, instead of
#     bailing on a non-fast-forward or a dirty tree.
#
# Installed at ~/.local/bin/run-memex-triage (see deploy/README.md). PATH must
# reach the uv-tool-installed `memex-triage` binary (commonly ~/.local/bin).
#
# Required env (sourced from ~/.secrets if present):
#   MEMEX_URL, MEMEX_CLIENT_ID, MEMEX_CLIENT_SECRET

set -euo pipefail

export PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"

# Load CF Access service-token creds + worker URL (and optionally VAULT_PATH/
# INBOX_PATH/TZ). systemd --user starts with a minimal environment.
[[ -f "$HOME/.secrets" ]] && source "$HOME/.secrets"

: "${MEMEX_URL:?MEMEX_URL must be set (provision ~/.secrets on this host)}"
: "${MEMEX_CLIENT_ID:?MEMEX_CLIENT_ID must be set}"
: "${MEMEX_CLIENT_SECRET:?MEMEX_CLIENT_SECRET must be set}"

VAULT="${VAULT_PATH:-$HOME/vault}"
INBOX_REL="${INBOX_PATH:-inbox/memex.md}"

memex-triage sync

cd "$VAULT"
if [[ -n "$(git status --porcelain -- "$INBOX_REL")" ]]; then
    git add -- "$INBOX_REL"
    git commit -m "memex-triage: deliver captures $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    git pull --rebase --autostash --quiet
    git push || { git pull --rebase --autostash --quiet && git push; }
fi
