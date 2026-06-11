#!/usr/bin/env bash
# db/migrate.sh — boring, deterministic migration runner.
#
# Applies db/migrations/NNNN_*.sql in filename order against $PG_DSN,
# recording each applied file in ops.schema_migrations. Re-runs are
# idempotent: already-recorded files are skipped. Each migration is applied
# and recorded in ONE transaction (psql -1 wraps the -f and the bookkeeping
# -c together), so a failed migration leaves no half-state.
#
# Requires an admin/owner connection (CREATE SCHEMA / CREATE ROLE / GRANT).
# Steady-state jobs never run this — see db/README.md ("apply gate").
#
# Usage:
#   export PG_DSN='postgresql://<admin>@<pg-host>:5432/<db>'
#   ./migrate.sh --dry-run   # print what would apply, change nothing
#   ./migrate.sh             # apply pending migrations

set -euo pipefail

### ── args / env ──────────────────────────────────────────────────────────────

DRY_RUN=0
for arg in "$@"; do
    case "$arg" in
        --dry-run) DRY_RUN=1 ;;
        *) echo "usage: $0 [--dry-run]" >&2; exit 2 ;;
    esac
done

: "${PG_DSN:?PG_DSN must be set (admin/owner DSN; see db/README.md)}"
command -v psql >/dev/null || { echo "error: psql not found in PATH" >&2; exit 1; }

MIGRATIONS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/migrations" && pwd)"
PSQL=(psql "$PG_DSN" -X -q -v ON_ERROR_STOP=1)

### ── bookkeeping table (runner-owned, not a migration) ───────────────────────
# Must exist before the first migration can be recorded, so the runner
# bootstraps it. --dry-run must not create anything.

if [[ $DRY_RUN -eq 0 ]]; then
    "${PSQL[@]}" \
        -c "CREATE SCHEMA IF NOT EXISTS ops;" \
        -c "CREATE TABLE IF NOT EXISTS ops.schema_migrations (
                version    text PRIMARY KEY,
                applied_at timestamptz NOT NULL DEFAULT now()
            );"
fi

# On a fresh DB under --dry-run the table doesn't exist yet: treat as empty.
applied="$("${PSQL[@]}" -At -c "SELECT version FROM ops.schema_migrations" 2>/dev/null || true)"

### ── apply pending migrations in order ───────────────────────────────────────

shopt -s nullglob
pending=0
for file in "$MIGRATIONS_DIR"/[0-9]*.sql; do
    version="$(basename "$file")"
    if grep -qxF "$version" <<<"$applied"; then
        echo "skip   $version (already applied)"
        continue
    fi
    pending=$((pending + 1))
    if [[ $DRY_RUN -eq 1 ]]; then
        echo "would apply  $version"
        continue
    fi
    echo "apply  $version"
    "${PSQL[@]}" -1 \
        -f "$file" \
        -c "INSERT INTO ops.schema_migrations (version) VALUES ('$version');"
done

if [[ $DRY_RUN -eq 1 ]]; then
    echo "dry-run: $pending migration(s) pending"
else
    echo "done: $pending migration(s) applied"
fi
