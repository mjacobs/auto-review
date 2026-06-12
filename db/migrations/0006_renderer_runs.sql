-- 0006_renderer_runs.sql — let the check-in renderer record its own runs
-- (auto-review-hg6.5; renderer/DESIGN.md decision 5, which settles db/README
-- open question 1).
--
-- 0005_roles.sql created checkin_renderer strictly read-only. The renderer
-- design ruled that the renderer records its own ops.job_runs row — the
-- memex-sync pattern: main work first, then a separate connection inserts an
-- 'ok' row with a summary, and a best-effort 'error' row on exception. A
-- wrapper-recorded row under a second role would mean a second credential on
-- the host for zero security gain, and doctor-observed liveness via git
-- commits is exactly the regex-the-serialization pattern this epic deletes.
-- Append-only INSERT cannot corrupt anything the renderer reads, and the
-- doctor precedent (0005) already establishes "read-only across domains +
-- INSERT on job_runs" as a coherent privilege shape.
--
-- Requires ops.jobs rows for the renderer (daily, later weekly/monthly)
-- seeded at deploy time — the job_runs FK is the registry enforcement.
-- Idempotent: GRANT is naturally re-runnable.

-- USAGE on ops was already granted in 0005_roles.sql; repeated here so this
-- migration also stands alone against a scratch DB.
GRANT USAGE ON SCHEMA ops TO checkin_renderer;

-- job_runs stays append-only for the renderer like every other job role:
-- INSERT and nothing else here (its SELECT on ops.jobs/ops.job_runs for the
-- health section came with 0005).
GRANT INSERT ON ops.job_runs TO checkin_renderer;
