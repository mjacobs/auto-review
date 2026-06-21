-- 0009_auto_review_doctor_job.sql — register auto-review-doctor in ops.jobs so
-- it can write its OWN ops.job_runs row each run (auto-review-02w).
--
-- g52 gave the doctor in-band self-liveness (a 7-day lookback that flags missed
-- doctor runs the moment the doctor recovers). Its inherent limit: it cannot fire
-- while the doctor is FULLY down — nothing runs to report. The fix is to make the
-- doctor record a row in ops.job_runs at the end of every run, so "latest doctor
-- row age" becomes a queryable dead-man substrate that ANY independent process
-- with PG read access can check in one line:
--
--   SELECT now() - max(finished_at) FROM ops.job_runs WHERE job_name = 'auto-review-doctor';
--
-- That moves the who-watches-the-watcher check OUT of the doctor itself, without
-- reintroducing a second check-in writer (the contention g52 avoided).
--
-- The job_runs.job_name -> ops.jobs.name FK blocks any insert until a registry
-- row exists, so THIS MIGRATION MUST BE APPLIED BEFORE the doctor first records a
-- row (it otherwise errors on the FK and silently swallows the failure). The
-- auto_review_doctor role already holds INSERT on ops.job_runs (db/migrations/
-- 0005 — described there as "read-only + records its runs"); no new grant needed.
--
-- expected_interval is the max age of the latest run before "overdue". The doctor
-- runs as the LAST phase of run-checkin-nightly (~00:22 PT), so its freshest row
-- is normally minutes old at any external-checker time. 26h (24h + 2h grace) is
-- the siblings' calibration (0007/0008), reused: it flags the doctor dead for a
-- full day without false-flagging a slow/late nightly run. monitored = true so
-- ops.jobs is an honest record of the doctor's own liveness too; the doctor does
-- NOT add a pg_job_name self-check to its own JOBS list (that would have g52's
-- same watcher-flaw) — the row is an EXTERNAL substrate, checked off-host.
--
-- Idempotent: INSERT ... ON CONFLICT (name) DO UPDATE (mirrors 0007/0008), so
-- re-runs and any later cadence tweak are safe. The CHECK (NOT monitored OR
-- expected_interval IS NOT NULL) on ops.jobs is why expected_interval is set in
-- the same statement that flips monitored=true.

INSERT INTO ops.jobs (name, host, cadence, writes, monitored, expected_interval)
VALUES (
    'auto-review-doctor',
    'auto-review-lxc',
    'via run-checkin-nightly (last phase, ~00:22 PT)',
    'check-in § (health) + ops.job_runs (own dead-man row)',
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
