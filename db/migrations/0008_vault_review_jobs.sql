-- 0008_vault_review_jobs.sql — register vault-review (daily + weekly) in
-- ops.jobs so it can write ops.job_runs, completing the doctor's exit from the
-- cron.log-commit + check-in-marker liveness path (auto-review-2vv).
--
-- vault-review was the LAST monitored job still checked via the log/marker path,
-- which is blind to log rotation (demonstrated 2026-06-13: a mid-afternoon doctor
-- run showed vault-review ❌ never because its 00:01 commit had rotated out of
-- the current cron.log, while the 3 PG jobs correctly showed ✓ — job_runs is
-- rotation-independent). hg6.8 moved memex-sync/agent-review/renderer onto
-- job_runs; this finishes the migration for vault-review.
--
-- The vault_review_job role already holds INSERT on ops.job_runs (0005). The
-- job_runs.job_name -> ops.jobs.name FK blocks any insert until a registry row
-- exists, so THIS MIGRATION MUST BE APPLIED BEFORE the tool's first run records
-- a row (the cron wrapper / tool will otherwise error on the FK).
--
-- expected_interval is the max age of the latest run before "overdue":
--   * vault-review-daily fires 00:01 PT; the doctor runs 00:22 PT (LAST in the
--     nightly cluster), so the daily's freshest row is normally ~21 min old at
--     doctor time. The 26h window (24h + 2h grace) is the siblings' calibration,
--     reused — it flags a job dead for a full day without false-flagging a
--     slow/late nightly run (docs/schedules.md).
--   * vault-review-weekly fires Mon 00:08 PT. A flat age window would either stay
--     green for ~8 days after a real miss (8d interval) or false-positive every
--     Monday before the 00:08 fire (24h-ish interval — the hg6.12 BUG2 shape).
--     The doctor instead uses a SCHEDULE-AWARE check (most-recent expected Monday
--     fire vs the latest weekly row); 8 days + grace here is just the registry/
--     moving-pieces sanity bound and the FK target — not the live liveness math.
--
-- Idempotent: INSERT ... ON CONFLICT (name) DO UPDATE (mirrors 0007), so re-runs
-- and any later cadence tweak are safe. The CHECK (NOT monitored OR
-- expected_interval IS NOT NULL) on ops.jobs is why expected_interval is set in
-- the same statement that flips monitored=true.

INSERT INTO ops.jobs (name, host, cadence, writes, monitored, expected_interval)
VALUES (
    'vault-review-daily',
    'auto-review-lxc',
    '00:01 PT daily',
    'vault check-in § (daily recap, git-diff) + ops.job_runs',
    true,
    interval '26 hours'
)
ON CONFLICT (name) DO UPDATE SET
    host              = EXCLUDED.host,
    cadence           = EXCLUDED.cadence,
    writes            = EXCLUDED.writes,
    monitored         = EXCLUDED.monitored,
    expected_interval = EXCLUDED.expected_interval,
    retired_at        = NULL;

INSERT INTO ops.jobs (name, host, cadence, writes, monitored, expected_interval)
VALUES (
    'vault-review-weekly',
    'auto-review-lxc',
    'Mon 00:08 PT weekly',
    'vault weekly § (weekly recap, git-diff) + ops.job_runs',
    true,
    interval '8 days 2 hours'
)
ON CONFLICT (name) DO UPDATE SET
    host              = EXCLUDED.host,
    cadence           = EXCLUDED.cadence,
    writes            = EXCLUDED.writes,
    monitored         = EXCLUDED.monitored,
    expected_interval = EXCLUDED.expected_interval,
    retired_at        = NULL;
