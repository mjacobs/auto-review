#!/usr/bin/env bash
# db/set-role-passwords.sh — set role passwords out-of-band, from env.
#
# Passwords NEVER live in migration files or argv. For each composition-layer
# role this reads PGPASS_<ROLE_IN_CAPS> from the environment (source them from
# ~/.secrets, per repo convention) and runs ALTER ROLE via psql variable
# binding on stdin — the value never appears in a command line or SQL file.
# Roles with no matching env var are skipped, so this can set one password or
# all of them.
#
# Caveat: ALTER ROLE ... PASSWORD can still land in the SERVER log if
# log_statement is permissive. For a fully log-safe path, use \password <role>
# in an interactive psql session instead (it sends a pre-hashed password).
#
# Usage:
#   export PG_DSN='postgresql://<admin>@<pg-host>:5432/<db>'
#   export PGPASS_MEMEX_SYNC='...'           # etc.
#   ./set-role-passwords.sh

set -euo pipefail

: "${PG_DSN:?PG_DSN must be set (admin DSN)}"
command -v psql >/dev/null || { echo "error: psql not found in PATH" >&2; exit 1; }

ROLES=(
    memex_sync
    memex_review
    vault_review_job
    agent_review        # pre-existing live role; usually skip (already has one)
    auto_review_doctor
    checkin_renderer
    memex_triage
)

changed=0
for role in "${ROLES[@]}"; do
    var="PGPASS_${role^^}"
    if [[ -z "${!var:-}" ]]; then
        echo "skip   $role (\$$var not set)"
        continue
    fi
    psql "$PG_DSN" -X -q -v ON_ERROR_STOP=1 \
        -v role="$role" -v pw="${!var}" <<'SQL'
ALTER ROLE :"role" PASSWORD :'pw';
SQL
    echo "set    $role"
    changed=$((changed + 1))
done

echo "done: $changed password(s) set"
