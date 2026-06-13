-- 0007_agent_review_job.sql — register agent-review in ops.jobs so it can write
-- ops.job_runs, and flip the three PG-writer jobs to monitored (auto-review-hg6.8).
--
-- Step-A (hg6.4/hg6.6) left agent-review and the renderer emitting no git commit
-- line and no check-in marker — the only signals the doctor's old liveness check
-- read — so the two most load-bearing daily jobs went UNMONITORED. hg6.8 moves
-- doctor liveness onto ops.job_runs. The renderer and memex-sync already write
-- job_runs rows; agent-review did not, and the job_runs.job_name -> ops.jobs.name
-- FK blocks any insert until a registry row exists. This migration adds that row
-- (the agent_review role already holds INSERT on ops.job_runs from 0005), then
-- marks all three PG writers monitored so ops.jobs is an honest parallel record
-- of what the doctor watches (and what the renderer's future health view —
-- ops.jobs ⨝ latest job_runs — will read).
--
-- expected_interval is the max age of the latest run before "overdue". The doctor
-- runs 00:31 PT and monitors a DAY-OLD signal: it fires BEFORE the renderer
-- (00:51) and only ~10 min after agent-review (00:21, an LLM job that may still
-- be in flight), so a daily job's freshest row is normally ~24h old at doctor
-- time. 26h (24h + 2h grace) flags a job dead for a full day without false-
-- flagging an in-flight or slightly-late nightly run — the renderer's existing
-- calibration, reused. memex-sync (hourly) keeps its 2h window.
--
-- Idempotent: INSERT ... ON CONFLICT DO UPDATE; UPDATEs are naturally re-runnable.
-- The CHECK (NOT monitored OR expected_interval IS NOT NULL) on ops.jobs is why
-- expected_interval is set in the same statement that flips monitored.

INSERT INTO ops.jobs (name, host, cadence, writes, monitored, expected_interval)
VALUES (
    'agent-review',
    'auto-review-lxc',
    '00:21 PT daily',
    'agent_review.daily_reports (daily report row; --no-vault) + ops.job_runs',
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

-- The other two PG writers already have rows (seeded at their Phase deploys) with
-- expected_interval set but monitored=false; hg6.8 turns monitoring on.
UPDATE ops.jobs SET monitored = true
    WHERE name IN ('memex-sync', 'checkin-renderer-daily');
