#!/usr/bin/env bash
# db/verify.sh — post-apply verification for the composition-layer schema.
#
# Checks (read-only, against $PG_DSN):
#   - every migration file is recorded in ops.schema_migrations
#   - schemas and tables exist
#   - roles exist and can log in
#   - spot-check grants: writers can write their own tables; job_runs is
#     append-only (INSERT but not UPDATE); the renderer canNOT write anywhere
#     (least-privilege negatives)
#
# Exits nonzero on any mismatch. Safe to run as any role that can read the
# system catalogs (the admin used for migrate.sh is the natural choice).

set -euo pipefail

: "${PG_DSN:?PG_DSN must be set}"
command -v psql >/dev/null || { echo "error: psql not found in PATH" >&2; exit 1; }

MIGRATIONS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/migrations" && pwd)"
PSQL=(psql "$PG_DSN" -X -q -At -v ON_ERROR_STOP=1)

fail=0

# check <description> <sql-returning-boolean>
check() {
    local desc="$1" sql="$2" got
    if got="$("${PSQL[@]}" -c "$sql")" && [[ "$got" == "t" ]]; then
        echo "ok     $desc"
    else
        echo "FAIL   $desc"
        fail=1
    fi
}

### ── migrations recorded ─────────────────────────────────────────────────────

shopt -s nullglob
for file in "$MIGRATIONS_DIR"/[0-9]*.sql; do
    version="$(basename "$file")"
    check "migration recorded: $version" \
        "SELECT EXISTS (SELECT 1 FROM ops.schema_migrations WHERE version = '$version')"
done

### ── schemas ─────────────────────────────────────────────────────────────────

for schema in ops memex vault_review projects; do
    check "schema exists: $schema" \
        "SELECT EXISTS (SELECT 1 FROM information_schema.schemata WHERE schema_name = '$schema')"
done

### ── tables ──────────────────────────────────────────────────────────────────

for table in \
    ops.schema_migrations ops.jobs ops.job_runs \
    memex.captures memex.capture_triage memex.sync_state \
    vault_review.daily_digests vault_review.weekly_digests \
    projects.projects
do
    check "table exists: $table" \
        "SELECT to_regclass('$table') IS NOT NULL"
done

### ── roles ───────────────────────────────────────────────────────────────────

for role in memex_sync memex_review vault_review_job agent_review \
            auto_review_doctor checkin_renderer memex_triage
do
    check "role exists + LOGIN: $role" \
        "SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '$role' AND rolcanlogin)"
done

### ── grants: writers can write their own tables ──────────────────────────────

check "memex_sync can INSERT memex.captures" \
    "SELECT has_table_privilege('memex_sync', 'memex.captures', 'INSERT')"
check "memex_sync can INSERT memex.capture_triage" \
    "SELECT has_table_privilege('memex_sync', 'memex.capture_triage', 'INSERT')"
check "memex_sync can UPDATE memex.sync_state" \
    "SELECT has_table_privilege('memex_sync', 'memex.sync_state', 'UPDATE')"
check "vault_review_job can INSERT vault_review.daily_digests" \
    "SELECT has_table_privilege('vault_review_job', 'vault_review.daily_digests', 'INSERT')"
check "vault_review_job can INSERT vault_review.weekly_digests" \
    "SELECT has_table_privilege('vault_review_job', 'vault_review.weekly_digests', 'INSERT')"
check "memex_triage can UPDATE memex.capture_triage.state" \
    "SELECT has_column_privilege('memex_triage', 'memex.capture_triage', 'state', 'UPDATE')"
check "memex_triage can INSERT projects.projects" \
    "SELECT has_table_privilege('memex_triage', 'projects.projects', 'INSERT')"
check "memex_triage can UPDATE projects.projects" \
    "SELECT has_table_privilege('memex_triage', 'projects.projects', 'UPDATE')"

### ── grants: job_runs is append-only ─────────────────────────────────────────
# Every job role can INSERT; nobody (job roles included) can UPDATE or DELETE.

# checkin_renderer joined in 0006 (records its own runs; DESIGN.md decision 5).
for role in memex_sync memex_review vault_review_job agent_review auto_review_doctor checkin_renderer; do
    check "$role can INSERT ops.job_runs" \
        "SELECT has_table_privilege('$role', 'ops.job_runs', 'INSERT')"
    check "$role canNOT UPDATE/DELETE ops.job_runs (append-only)" \
        "SELECT NOT (has_any_column_privilege('$role', 'ops.job_runs', 'UPDATE')
                  OR has_table_privilege('$role', 'ops.job_runs', 'DELETE'))"
done

# the pre-existing agent_review role got INSERT on job_runs and NOTHING else new
check "agent_review canNOT SELECT ops.job_runs" \
    "SELECT NOT has_table_privilege('agent_review', 'ops.job_runs', 'SELECT')"
check "agent_review canNOT read memex.captures" \
    "SELECT NOT has_table_privilege('agent_review', 'memex.captures', 'SELECT')"

### ── grants: doctor + renderer read everything, write nothing ────────────────
# agent_review/agentsview tables are checked only when present (pre-existing
# schemas, granted conditionally in 0005).

for role in auto_review_doctor checkin_renderer; do
    for table in memex.captures memex.capture_triage memex.sync_state \
                 vault_review.daily_digests vault_review.weekly_digests \
                 projects.projects ops.jobs ops.job_runs
    do
        check "$role can SELECT $table" \
            "SELECT has_table_privilege('$role', '$table', 'SELECT')"
    done
    for table in agent_review.daily_reports agent_review.session_digests \
                 agentsview.sessions
    do
        check "$role can SELECT $table (if it exists)" \
            "SELECT CASE WHEN to_regclass('$table') IS NULL THEN true
                         ELSE has_table_privilege('$role', '$table', 'SELECT') END"
    done
done

# ops.job_runs is excluded: 0006 grants the renderer INSERT there (append-only,
# covered by the loop above) — it writes nothing else.
for table in memex.captures memex.capture_triage memex.sync_state \
             vault_review.daily_digests vault_review.weekly_digests \
             projects.projects ops.jobs
do
    check "checkin_renderer canNOT write $table" \
        "SELECT NOT (has_table_privilege('checkin_renderer', '$table', 'INSERT')
                  OR has_any_column_privilege('checkin_renderer', '$table', 'UPDATE')
                  OR has_table_privilege('checkin_renderer', '$table', 'DELETE'))"
done

check "auto_review_doctor canNOT write memex.captures" \
    "SELECT NOT (has_table_privilege('auto_review_doctor', 'memex.captures', 'INSERT')
              OR has_any_column_privilege('auto_review_doctor', 'memex.captures', 'UPDATE'))"

### ── grants: least-privilege negatives ───────────────────────────────────────

check "memex_triage canNOT write memex.captures" \
    "SELECT NOT (has_table_privilege('memex_triage', 'memex.captures', 'INSERT')
              OR has_any_column_privilege('memex_triage', 'memex.captures', 'UPDATE'))"
check "memex_triage canNOT DELETE projects.projects (retire via status)" \
    "SELECT NOT has_table_privilege('memex_triage', 'projects.projects', 'DELETE')"
check "memex_review canNOT write memex.captures" \
    "SELECT NOT (has_table_privilege('memex_review', 'memex.captures', 'INSERT')
              OR has_any_column_privilege('memex_review', 'memex.captures', 'UPDATE'))"
check "memex_sync canNOT UPDATE memex.capture_triage (state is triage-owned)" \
    "SELECT NOT has_any_column_privilege('memex_sync', 'memex.capture_triage', 'UPDATE')"
check "vault_review_job canNOT write memex.captures" \
    "SELECT NOT (has_table_privilege('vault_review_job', 'memex.captures', 'INSERT')
              OR has_any_column_privilege('vault_review_job', 'memex.captures', 'UPDATE'))"
check "memex_triage canNOT INSERT ops.job_runs (not a periodic job)" \
    "SELECT NOT has_table_privilege('memex_triage', 'ops.job_runs', 'INSERT')"

### ── result ──────────────────────────────────────────────────────────────────

if [[ $fail -ne 0 ]]; then
    echo "verify: FAILED (see FAIL lines above)" >&2
    exit 1
fi
echo "verify: all checks passed"
