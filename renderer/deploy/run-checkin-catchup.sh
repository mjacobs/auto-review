#!/usr/bin/env bash
# Midday check-in catch-up — the producer→renderer race stopgap (auto-review-hg6.11,
# OPTION 3).
#
# The renderer is date-driven, stateless, and idempotent. When a producer
# (here: agent-review) transiently fails at ~00:08 PT and persists NO PG row,
# the 00:19 renderer finds the row missing and bakes a permanent-looking
# placeholder ("_no agent-review report row for D_") into note D. Nothing
# re-runs to replace it — recovery is otherwise fully manual (the 2026-06-15
# incident: the LLM gateway was briefly down, tenacity retries exhausted, no
# daily_reports[2026-06-15] row).
#
# This wrapper runs midday (~10:00 PT — hours after the 00:08 producer run, so a
# transient gateway/DB blip has had time to clear) and is GAP-GATED: it queries
# Postgres read-only for the producer's RUN STATUS for yesterday and ONLY
# re-runs the producer + renderer if that run FAILED or never landed. On the
# common no-gap day — including a legitimately quiet zero-session day — it logs
# and exits 0, a clean no-op. Both `agent-review run D --no-vault` and
# `checkin-renderer run D` are idempotent, so a re-run cleanly REPLACES the
# placeholder with the real section (confirmed by the manual backfill in the
# hg6.11 incident).
#
# Why gate on ops.job_runs, not agent_review.daily_reports presence: a quiet day
# with zero in-scope sessions persists NO daily_reports row (agent-review/src/
# agent_review/cli.py _run_one) yet is a fully SUCCESSFUL run — agent-review
# still records a status='ok' job_runs row covering D. Gating on daily_reports
# presence alone (the original v0) would mistake every quiet day for a producer
# failure and take the backfill branch needlessly. The transient incident this
# stopgap targets is distinguishable from a quiet day precisely here: a failed
# run records status='error' (or, on a hard crash before recording, no row at
# all), whereas a quiet day records status='ok'. So the gap signal is "no 'ok'
# agent-review run covering D", which fires for the incident and stays a no-op
# for both a normal report day and a quiet zero-session day.
#
# Because it legitimately no-ops on most days, the doctor catalogs it with
# monitored=False (a conditional job must NOT be liveness-monitored, or the
# doctor false-positives every quiet day). See doctor/auto-review-doctor JOBS.
#
# v0 scope: the agent-review producer only — the documented incident. The same
# placeholder reproduces for the vault and memex sections on a pre-render blip;
# broadening this catch-up to those producers is a follow-up (auto-review-hg6.11
# names them). Keep the gap query producer-specific.
#
# Installed at ~/.local/bin/run-checkin-catchup on the cron host and invoked
# from the user crontab by hand (the crontab is hand-maintained — see
# docs/schedules.md and AGENTS.md; tooling never auto-edits it):
#   0 10 * * *  run-checkin-catchup >> ~/.local/state/auto-review/cron.log 2>&1
# PATH must include the directory holding the uv-tool-installed `agent-review`
# and `checkin-renderer` binaries (commonly ~/.local/bin).
#
# Required env (sourced from ~/.secrets if present) — the SAME vars the two
# daily wrappers this stitches together already require:
#   PG_DSN                   postgresql://agent_review@<pg-host>:5432/<db> — the
#                            agent_review role's DSN (as in run-agent-review-
#                            daily.sh). Used here by the re-run of agent-review
#                            itself. NOT used for the gap probe: the agent_review
#                            role holds INSERT-only on ops.job_runs (no SELECT —
#                            db/migrations/0005), so it cannot read run status.
#   CHECKIN_RENDERER_PG_DSN  the checkin_renderer role's DSN (as in run-checkin-
#                            renderer-daily.sh) — the renderer reads it to
#                            compose note D and record its ops.job_runs row. Used
#                            READ-ONLY here for the gap probe too: this role is
#                            the one granted SELECT on ops.job_runs (0005), so it
#                            is the right credential to read agent-review's run
#                            status for D.
# Optional env:
#   VAULT_PATH               vault checkout root (default: ~/vault), for the
#                            commit/push of the re-rendered note.
#   LLM_BACKEND / MODEL_*    forwarded to agent-review's re-run exactly as the
#                            daily wrapper documents (claude_cli default).

set -euo pipefail

export PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"

# Load credentials. Cron starts with a minimal environment.
[[ -f "$HOME/.secrets" ]] && source "$HOME/.secrets"

: "${PG_DSN:?PG_DSN must be set (provision ~/.secrets on this host)}"
: "${CHECKIN_RENDERER_PG_DSN:?CHECKIN_RENDERER_PG_DSN must be set (provision ~/.secrets on this host)}"

VAULT="${VAULT_PATH:-$HOME/vault}"

log() {
    printf '%s run-checkin-catchup: %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"
}

# D = yesterday, computed in the host's local TZ (the LXC is pinned to
# America/Los_Angeles), matching the `yesterday` every daily job reports on.
D="$(date -d 'yesterday' +%Y-%m-%d)"

# Gap detection: read-only probe for a SUCCESSFUL producer run covering D.
#
# We gate on run status (ops.job_runs), NOT daily_reports presence, so a quiet
# zero-session day — a successful run that legitimately persists no report row —
# is correctly treated as no-gap. agent-review records exactly one job_runs row
# per `run`: status='ok' on success (including a quiet day), status='error' on a
# handled failure, and NO row at all on a hard crash before recording. The row
# covering D is the one whose summary->'dates' JSON array contains D (the daily
# run reports on `yesterday`, i.e. D, at ~00:08 on D+1). "An 'ok' run for D
# exists" therefore means: no gap. Anything else (only 'error' rows, or no row)
# means: gap.
#
# `-At` (unaligned, tuples-only) makes a matching row emit exactly "1" and no
# match emit nothing, so an empty result == gap. ON_ERROR_STOP=1 makes a real DB
# error (vs an empty result set) fail the script under `set -e` rather than
# masquerade as "no gap" and trigger a needless re-run. The probe uses
# CHECKIN_RENDERER_PG_DSN: the checkin_renderer role is the one granted SELECT on
# ops.job_runs (the agent_review role behind PG_DSN has INSERT-only there).
row="$(psql "$CHECKIN_RENDERER_PG_DSN" -At -v ON_ERROR_STOP=1 \
    -c "SELECT 1 FROM ops.job_runs
         WHERE job_name = 'agent-review'
           AND status = 'ok'
           AND summary -> 'dates' @> to_jsonb('$D'::text)
         LIMIT 1")"

if [[ -n "$row" ]]; then
    log "no backfill needed for $D (agent-review recorded an ok run covering $D)"
    exit 0
fi

# Gap confirmed: no successful agent-review run covering D (a failed run or none
# at all), so the renderer baked a placeholder. Re-run both — idempotent, so
# this REPLACES the placeholder.
log "gap detected for $D (no ok agent-review run covering $D) — backfilling"

# Producer: --no-vault writes the PG row only (ADR 002; the renderer owns the
# vault projection). The renderer below commits/pushes the note.
log "re-running agent-review for $D"
agent-review run "$D" --no-vault

# Renderer: re-composes note D from the now-present PG rows, replacing the
# placeholder section in the note file (it does NOT git-push — the wrapper owns
# that path, AGENTS.md).
log "re-rendering check-in note for $D"
checkin-renderer run "$D"

# Commit + push the re-rendered note, mirroring run-checkin-renderer-daily.sh:
# the wrapper owns the git path, and pull --rebase + one retry absorbs a
# concurrent vault push (auto-review-qgo). No change => nothing to commit.
cd "$VAULT"
if [[ -n "$(git status --porcelain)" ]]; then
    git add -A
    git commit -m "checkin-renderer: catch-up backfill $D ($(date -u +%Y-%m-%dT%H:%M:%SZ))"
    git pull --rebase --quiet
    git push || { git pull --rebase --quiet && git push; }
    log "pushed backfilled note for $D"
else
    log "re-render produced no note change for $D (already current)"
fi

log "backfill complete for $D"
