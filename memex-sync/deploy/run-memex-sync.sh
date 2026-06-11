#!/usr/bin/env bash
# memex-sync cron wrapper.
#
# Runs `memex-sync sync`: pulls new captures from the cf-memex change feed
# into the Postgres memex schema, advances the watermark, and records an
# ops.job_runs row. Unlike the sibling wrappers there is NO vault/git step —
# this tool touches no files; the database row IS the side effect, and the
# tool records its own run row (an idle run still inserts one, which is the
# doctor's liveness evidence). A crashed run inserts nothing and simply goes
# overdue under the doctor's liveness query — that is by design (see
# db/README.md "append-only").
#
# Installed at ~/.local/bin/run-memex-sync on the cron host and invoked from
# the user crontab. PATH must include the directory holding the
# uv-tool-installed `memex-sync` binary (commonly ~/.local/bin).
#
# Required env (sourced from ~/.secrets if present):
#   MEMEX_SYNC_PG_DSN    postgresql://memex_sync@<pg-host>:5432/<db>
#                        (password may instead come from ~/.pgpass).
#                        Dedicated var because ~/.secrets PG_DSN on the cron
#                        host belongs to the agent_review role, which has no
#                        memex grants; falls back to PG_DSN if unset.
#   MEMEX_URL, MEMEX_CLIENT_ID, MEMEX_CLIENT_SECRET
#
# Optional:
#   MEMEX_SYNC_CONSUMER  sync_state key        (default: memex_sync)
#   MEMEX_SYNC_JOB_NAME  ops.jobs name         (default: memex-sync)
#   MEMEX_SYNC_HOST      ops.job_runs host     (default: hostname)

set -euo pipefail

export PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"

# Load PG + CF Access creds. Cron starts with a minimal environment.
[[ -f "$HOME/.secrets" ]] && source "$HOME/.secrets"

# Prefer the role-scoped DSN; the shared PG_DSN is another sibling's role.
export PG_DSN="${MEMEX_SYNC_PG_DSN:-${PG_DSN:-}}"

: "${PG_DSN:?MEMEX_SYNC_PG_DSN (or PG_DSN) must be set (provision ~/.secrets on this host)}"
: "${MEMEX_URL:?MEMEX_URL must be set}"
: "${MEMEX_CLIENT_ID:?MEMEX_CLIENT_ID must be set}"
: "${MEMEX_CLIENT_SECRET:?MEMEX_CLIENT_SECRET must be set}"

memex-sync sync
