#!/usr/bin/env bash
# run-checkin-nightly — single ordered driver for the auto-review nightly
# cluster (auto-review OMG-002 / the producer→renderer race fix).
#
# WHY THIS EXISTS
# The nightly jobs were independent crontab lines staggered by fixed time
# offsets (vault-review 00:01, agent-review 00:08, renderer 00:19, doctor
# 00:22). Those offsets were a PROXY for "wait until the previous job finished"
# — a fragile one, because the agent-review producer's runtime is unbounded: it
# is a serial loop of blocking `claude -p` digest calls, so wall-time scales
# with session count (~12 min for 23 sessions; more on a codex-spike day). On
# 2026-06-18 a slow producer finished 41 s AFTER the fixed-offset renderer had
# already read Postgres, so the renderer baked a "_no agent-review report row_"
# placeholder into the note (OMG-002).
#
# This driver replaces the staggered lines with ONE crontab entry that runs each
# phase IN DEPENDENCY ORDER and WAITS for it to finish. The renderer therefore
# runs because the producer COMPLETED, not because a clock guessed it would be
# done — the producer→renderer race is gone by construction. The doctor runs
# LAST as a phase, so "the doctor sees a settled note + every job_runs row" is
# structural, not a timing coincidence (retires the auto-review-hg6.12 class of
# doctor-ran-too-early false positive too).
#
# CRONTAB (hand-maintained; back up + diff + install per docs/schedules.md):
#   8 0 * * *  run-checkin-nightly >> $HOME/.local/state/auto-review/cron.log 2>&1
# Start 00:08 PT preserves the ~8-min margin after the EXTERNAL agentsview push
# (baox → agentsview PG at ~23:55/00:00) — the one edge a local wait cannot
# block on (docs/schedules.md buffer #1). memex-sync (hourly :05) and
# vault-sync-pull (*/5) keep their own cron lines; the 10:00 catch-up stays as a
# failure-only backstop.
#
# FAILURE ISOLATION — deliberately NOT `set -e`.
# Each phase runs in its own `timeout`-bounded subprocess; a failure or timeout
# is logged and SKIPPED, never fatal. A producer failure must STILL let the
# renderer run (it writes a visible, diagnosable placeholder) and the doctor run
# (it reports the failure): a partial note beats no note. Each phase wrapper is
# self-contained — it sources ~/.secrets, sets its own PATH, and owns its own
# git commit/push — so phases stay isolated and this driver stays a thin
# orchestrator over the existing, separately-tested wrappers.

set -uo pipefail   # NOT -e: a failed phase must not abort the chain.

export PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"

log() { printf '%s run-checkin-nightly: %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"; }

failures=0

# run_phase NAME TIMEOUT WRAPPER [args...]
# Runs a phase wrapper bounded by TIMEOUT, non-fatally: logs OK/FAILED/TIMEOUT
# and continues regardless so downstream phases (renderer, doctor) always run.
run_phase() {
    local name="$1" budget="$2"
    shift 2
    if ! command -v "$1" >/dev/null 2>&1; then
        log "phase $name SKIPPED — '$1' not on PATH"
        failures=$((failures + 1))
        return 0
    fi
    local start rc
    start=$(date +%s)
    log "phase $name START (timeout $budget)"
    timeout "$budget" "$@"
    rc=$?
    if [[ $rc -eq 0 ]]; then
        log "phase $name OK ($(($(date +%s) - start))s)"
    elif [[ $rc -eq 124 ]]; then
        log "phase $name TIMED OUT after $budget — continuing"
        failures=$((failures + 1))
    else
        log "phase $name FAILED (rc=$rc) — continuing"
        failures=$((failures + 1))
    fi
    return 0
}

log "nightly cluster start (host $(hostname), $(date +%Y-%m-%d' '%H:%M' '%Z))"

# 1. vault-review daily — deterministic git-diff recap. Independent of the PG
#    chain; first because it is fast and only git-serializes with later phases.
run_phase vault-daily 10m run-recap-daily

# 2. vault-review weekly — Mondays only. Must precede the doctor so its weekly
#    liveness read is current (auto-review-hg6.12). %u: 1=Monday.
if [[ "$(date +%u)" == "1" ]]; then
    run_phase vault-weekly 10m run-recap-weekly
fi

# 3. agent-review — the slow/variable producer (sequential claude -p digests;
#    runtime scales with session count). --no-vault: writes its PG row only, no
#    git. The generous timeout bounds a WEDGED claude -p (e.g. a network hang) so
#    it can't stall the whole chain; a legit long run is rare. On timeout the
#    renderer below still runs (placeholder) and the doctor + 10:00 catch-up
#    recover — degrades to the old behaviour, never worse.
run_phase agent-review 45m run-agent-review-daily

# 4. memex-sync — fold the hourly capture mirror in right before the render so
#    the memex section is provably fresh regardless of when this driver starts
#    (idempotent watermark sync; also runs on its own hourly cron).
run_phase memex-sync 10m run-memex-sync

# 5. check-in renderer — composes note D from the now-complete PG rows. Runs
#    AFTER the producer finished (not on a guessed offset), so the agent-review
#    section is the real section, never the race placeholder. Owns commit/push.
run_phase renderer 10m run-checkin-renderer-daily

# 6. doctor — LAST. Assesses the settled note + every job_runs row written above,
#    then writes its health section. Running it as the final phase makes "the
#    doctor sees everything" structural rather than a timing guess.
run_phase doctor 10m run-auto-review-doctor

if [[ $failures -gt 0 ]]; then
    log "nightly cluster done with $failures phase failure(s)"
    exit 1
fi
log "nightly cluster done — all phases ok"
