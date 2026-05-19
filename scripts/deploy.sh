#!/usr/bin/env bash
# scripts/deploy.sh — deploy an auto-review sibling tool to openclaw.
#
# Usage:
#   ./scripts/deploy.sh <tool>
#   ./scripts/deploy.sh agent-review
#   ./scripts/deploy.sh vault-review
#   ./scripts/deploy.sh memex-review
#
# What it does:
#   1. cd into <tool>/, run `uv build`
#   2. scp the built wheel to openclaw:/tmp/
#   3. scp deploy/run-<wrapper>-daily.sh to openclaw:/tmp/ (if present)
#   4. ssh openclaw: uv tool install --reinstall; mv wrapper to ~/.local/bin/; chmod +x
#   5. Print secret-presence audit (counts only, never values)
#   6. Print the expected cron line for manual installation
#
# Hard constraints respected:
#   - Does NOT edit openclaw crontab (prints line for user to install)
#   - Does NOT write to openclaw:~/.secrets (prints presence audit only)
#   - Idempotent: --reinstall for uv tool, mv -f for wrapper
#   - ssh/scp use -o BatchMode=yes (non-interactive; fails cleanly if no key)
#
# Per AGENTS.md: user must confirm before running uv tool install / wrapper
# drops. This script prompts once before the remote install step.

set -euo pipefail

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

OPENCLAW_HOST="openclaw@OPENCLAW_HOST"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Tool metadata: wrapper name, cron line, required-secret grep patterns,
# and whether to check ~/.pgpass line count.
# Format: <wrapper>|<cron-line>|<secret-grep-pattern>|<check-pgpass: 0|1>

declare -A TOOL_WRAPPER=(
  [agent-review]="run-agent-review-daily"
  [vault-review]="run-recap-daily"
  [memex-review]="run-memex-review-daily"
)

declare -A TOOL_CRON=(
  [agent-review]="1 21 * * *  run-agent-review-daily  >> /home/openclaw/.local/state/vault-agent/cron.log 2>&1"
  [vault-review]="1 20 * * *  run-recap-daily          >> /home/openclaw/.local/state/vault-agent/cron.log 2>&1"
  [memex-review]="31 20 * * *  run-memex-review-daily  >> /home/openclaw/.local/state/vault-agent/cron.log 2>&1"
)

# Grep patterns to check in ~/.secrets (space-separated list per tool).
declare -A TOOL_SECRET_PATTERNS=(
  [agent-review]="^export PG_DSN= ^export ANTHROPIC_API_KEY="
  [vault-review]=""
  [memex-review]="^export MEMEX_URL= ^export MEMEX_CLIENT_ID= ^export MEMEX_CLIENT_SECRET="
)

# Whether to count ~/.pgpass lines for this tool.
declare -A TOOL_CHECK_PGPASS=(
  [agent-review]=1
  [vault-review]=0
  [memex-review]=0
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

log()  { printf '\033[1;34m==> %s\033[0m\n' "$*"; }
ok()   { printf '\033[1;32m  ok: %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m warn: %s\033[0m\n' "$*"; }
die()  { printf '\033[1;31merror: %s\033[0m\n' "$*" >&2; exit 1; }

usage() {
  printf 'Usage: %s <tool>\n' "$(basename "$0")"
  printf '  tool: agent-review | vault-review | memex-review\n'
  exit 1
}

# ---------------------------------------------------------------------------
# Argument validation
# ---------------------------------------------------------------------------

[[ $# -eq 1 ]] || usage
TOOL="$1"

[[ -v TOOL_WRAPPER[$TOOL] ]] || {
  warn "Unknown tool: $TOOL"
  usage
}

WRAPPER="${TOOL_WRAPPER[$TOOL]}"
TOOL_DIR="$REPO_ROOT/$TOOL"
DEPLOY_DIR="$TOOL_DIR/deploy"
WRAPPER_SH="$DEPLOY_DIR/${WRAPPER}.sh"
CRON_LINE="${TOOL_CRON[$TOOL]}"

[[ -d "$TOOL_DIR" ]] || die "Tool directory not found: $TOOL_DIR"

# ---------------------------------------------------------------------------
# Step 1: build wheel
# ---------------------------------------------------------------------------

log "Building $TOOL wheel"
cd "$TOOL_DIR"
uv build --quiet
WHEEL=$(ls -t dist/*.whl 2>/dev/null | head -1)
[[ -n "$WHEEL" ]] || die "No wheel found in $TOOL_DIR/dist/ after build"
ok "Wheel: $WHEEL"

# ---------------------------------------------------------------------------
# Step 2: scp wheel to openclaw
# ---------------------------------------------------------------------------

log "Uploading wheel to openclaw:/tmp/"
scp -o BatchMode=yes "$WHEEL" "$OPENCLAW_HOST:/tmp/"
ok "Wheel uploaded: $(basename "$WHEEL")"

# ---------------------------------------------------------------------------
# Step 3: scp wrapper script (if present)
# ---------------------------------------------------------------------------

HAVE_WRAPPER=0
if [[ -f "$WRAPPER_SH" ]]; then
  log "Uploading wrapper script to openclaw:/tmp/"
  scp -o BatchMode=yes "$WRAPPER_SH" "$OPENCLAW_HOST:/tmp/${WRAPPER}.sh"
  ok "Wrapper uploaded: ${WRAPPER}.sh"
  HAVE_WRAPPER=1
else
  warn "No wrapper script found at $WRAPPER_SH — skipping wrapper upload/install"
fi

# ---------------------------------------------------------------------------
# Step 4: remote install (with user confirmation)
# ---------------------------------------------------------------------------

WHEEL_BASENAME="$(basename "$WHEEL")"

log "Remote install step"
printf '\n  This will run on openclaw:\n'
printf '    uv tool install --reinstall /tmp/%s\n' "$WHEEL_BASENAME"
if [[ $HAVE_WRAPPER -eq 1 ]]; then
  printf '    mv -f /tmp/%s.sh ~/.local/bin/%s\n' "$WRAPPER" "$WRAPPER"
  printf '    chmod +x ~/.local/bin/%s\n' "$WRAPPER"
fi
printf '\n  Per project policy (AGENTS.md), user confirmation is required.\n'
printf '  Proceed? [y/N] '
read -r CONFIRM
[[ "$CONFIRM" =~ ^[Yy]$ ]] || { warn "Aborted by user."; exit 0; }

REMOTE_CMD="uv tool install --reinstall /tmp/${WHEEL_BASENAME}"
if [[ $HAVE_WRAPPER -eq 1 ]]; then
  REMOTE_CMD+=" && mv -f /tmp/${WRAPPER}.sh \$HOME/.local/bin/${WRAPPER} && chmod +x \$HOME/.local/bin/${WRAPPER}"
fi

ssh -o BatchMode=yes "$OPENCLAW_HOST" "$REMOTE_CMD"
ok "Remote install complete"

# ---------------------------------------------------------------------------
# Step 5: secret-presence audit (counts only, never values)
# ---------------------------------------------------------------------------

log "Secret-presence audit on openclaw (counts only, no values printed)"

SECRET_PATTERNS="${TOOL_SECRET_PATTERNS[$TOOL]}"
if [[ -n "$SECRET_PATTERNS" ]]; then
  for pattern in $SECRET_PATTERNS; do
    VAR_NAME="${pattern#^export }"
    VAR_NAME="${VAR_NAME%=}"
    COUNT=$(ssh -o BatchMode=yes "$OPENCLAW_HOST" \
      "grep -c '${pattern}' \"\$HOME/.secrets\" 2>/dev/null || echo 0")
    if [[ "$COUNT" -ge 1 ]]; then
      ok "$VAR_NAME present in ~/.secrets ($COUNT line(s))"
    else
      warn "$VAR_NAME NOT found in openclaw:~/.secrets — provision before running"
    fi
  done
else
  ok "No secrets required for $TOOL"
fi

if [[ "${TOOL_CHECK_PGPASS[$TOOL]}" -eq 1 ]]; then
  PGPASS_COUNT=$(ssh -o BatchMode=yes "$OPENCLAW_HOST" \
    "wc -l < \"\$HOME/.pgpass\" 2>/dev/null || echo 0")
  ok "~/.pgpass: $PGPASS_COUNT line(s) (non-zero = provisioned)"
fi

# ---------------------------------------------------------------------------
# Step 6: print cron line for manual installation
# ---------------------------------------------------------------------------

printf '\n'
log "Expected cron entry (add manually via: ssh openclaw crontab -e)"
printf '\n  %s\n\n' "$CRON_LINE"
warn "Project policy: do NOT auto-edit the crontab. User installs the line above."

printf '\n'
ok "$TOOL deploy complete"
