-- 0001_ops.sql — ops schema: job registry + job_runs.
--
-- The substrate for auto-review-hg6.8 (doctor over job_runs) and the
-- replacement for the JOBS dataclass + markdown-marker parsing in
-- doctor/auto-review-doctor. Idempotent: safe to re-run.
--
-- Note: ops.schema_migrations (the runner's bookkeeping table) is created by
-- db/migrate.sh itself, not by a migration — the table must exist before the
-- first migration can be recorded.

CREATE SCHEMA IF NOT EXISTS ops;

-- ─── job registry ─────────────────────────────────────────────────────────────
-- Mirrors the Job dataclass in doctor/auto-review-doctor (name/host/cadence/
-- writes/monitored). The markdown-era liveness fields (hhmm, commit_regex,
-- marker_tool, marker_key, is_weekly) are deliberately NOT carried over: in
-- the DB world liveness is "latest job_runs row vs expected_interval", so the
-- regex/marker plumbing is what this table exists to delete (hg6.8).
--
-- Seeding: intentionally no INSERTs here. The registry rows name internal
-- hosts, which stay out of this public repo; seed at apply time from the
-- doctor's JOBS registry (hg6.8 work).
CREATE TABLE IF NOT EXISTS ops.jobs (
    name              text PRIMARY KEY,
    host              text NOT NULL,
    cadence           text NOT NULL,          -- human-readable, for the moving-pieces view
    writes            text NOT NULL,          -- what the job produces, for the moving-pieces view
    monitored         boolean NOT NULL DEFAULT false,
    expected_interval interval,               -- liveness: overdue when now() - latest run > this
    registered_at     timestamptz NOT NULL DEFAULT now(),
    retired_at        timestamptz,            -- soft retire: keeps job_runs history FK-valid
    CHECK ((NOT monitored) OR expected_interval IS NOT NULL)
);

-- ─── job runs ─────────────────────────────────────────────────────────────────
-- One row per run of every periodic job; APPEND-ONLY (rows are immutable —
-- job roles get INSERT and nothing else, see 0005_roles.sql). A job inserts
-- exactly one row when it finishes (its wrapper inserts an 'error' row on
-- failure); a crashed/hung job inserts nothing and simply goes overdue.
-- Designed for exactly two query shapes (hg6.8):
--   liveness:  latest row per job (LEFT JOIN LATERAL ... ORDER BY started_at
--              DESC LIMIT 1) compared against ops.jobs.expected_interval
--   cost:      SUM(cost_usd) over a started_at window
-- The append-only shape also keeps the pre-existing agent_review role's new
-- privilege to exactly "INSERT ON ops.job_runs" (hg6.2 access decision).
-- The FK to ops.jobs is intentional: a job must be registered before its
-- first run-row lands, which is what keeps the registry current (AGENTS.md's
-- "any change to the periodic-job stack MUST update the registry", enforced).
CREATE TABLE IF NOT EXISTS ops.job_runs (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    job_name    text NOT NULL REFERENCES ops.jobs(name) ON UPDATE CASCADE,
    host        text NOT NULL,
    started_at  timestamptz NOT NULL,          -- supplied by the job (no default:
                                               -- a now() default would fake durations)
    finished_at timestamptz NOT NULL DEFAULT now(),
    status      text NOT NULL CHECK (status IN ('ok', 'error')),
    cost_usd    numeric(10, 4),               -- NULL for non-LLM jobs; SUM() for cost tracking
    summary     jsonb NOT NULL DEFAULT '{}'::jsonb,
    CHECK (finished_at >= started_at)
);

-- liveness: latest-row-per-job
CREATE INDEX IF NOT EXISTS idx_job_runs_job_started
    ON ops.job_runs (job_name, started_at DESC);

-- cost: SUM over a time window across jobs
CREATE INDEX IF NOT EXISTS idx_job_runs_started
    ON ops.job_runs (started_at);

-- (A separate ops.heartbeats table was considered for the dead-man substrate
-- (auto-review-02w) and dropped as speculative: per hg6.8 "a heartbeat row in
-- job_runs is the natural deadman substrate" — a beat is just a tiny job_runs
-- insert. See db/README.md open questions.)
