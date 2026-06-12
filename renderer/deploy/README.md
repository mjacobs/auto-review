# checkin-renderer — deploy

Runs on the auto-review LXC (the cron host from ADR 001), like every other
periodic job: vault checkout, cron, `~/.secrets`.

## Install (Phase 2, gated per AGENTS.md)

```bash
cd ~/dev/projects/auto-review/renderer
uv build
scp dist/checkin_renderer-*.whl deploy/run-checkin-renderer-daily.sh <cron-host>:/tmp/
ssh <cron-host> 'uv tool install --reinstall /tmp/checkin_renderer-*.whl && \
  mv -f /tmp/run-checkin-renderer-daily.sh ~/.local/bin/run-checkin-renderer-daily && \
  chmod +x ~/.local/bin/run-checkin-renderer-daily'
```

## Prerequisites (Phase 0, admin-gated)

1. Apply `db/migrations/0006_renderer_runs.sql` (INSERT on ops.job_runs for
   `checkin_renderer`).
2. Provision the `checkin_renderer` role password (`db/set-role-passwords.sh`
   or `\password`), add the `~/.pgpass` line on the cron host.
3. `CHECKIN_RENDERER_PG_DSN` in the host's `~/.secrets` (role-scoped var —
   the host's plain `PG_DSN` belongs to agent_review):
   `export CHECKIN_RENDERER_PG_DSN='postgresql://checkin_renderer@<pg-host>:5432/<db>'`
4. Seed the `ops.jobs` registry row for the daily job (FK enforcement —
   required before the first run row); weekly/monthly rows land with their
   crons in Phases 3/4. Update the doctor's `JOBS` registry in the same
   change (AGENTS.md rule).

## Cron lines

```
# daily: after the remaining 00:0x writer chain and the 00:41 hourly
# memex-sync, so captures made 23:41–midnight are mirrored before
# yesterday's window renders (DESIGN.md decision 4).
51 0 * * *   . ~/.secrets && run-checkin-renderer-daily >> ~/.local/state/auto-review/cron.log 2>&1

# weekly (Phase 3 / step C — replaces vault-review's weekly cron):
# 1 10 * * 1   . ~/.secrets && checkin-renderer run-weekly last-week …

# monthly (Phase 4 / auto-review-2l1):
# 21 10 1 * *  . ~/.secrets && checkin-renderer run-monthly last-month …
```

First live write is gated on user confirmation (AGENTS.md), preceded by a
`checkin-renderer run yesterday --dry-run --print` golden diff against the
real current note.
