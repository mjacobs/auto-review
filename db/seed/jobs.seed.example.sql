-- db/seed/jobs.seed.example.sql — sanitized SHAPE of the ops.jobs registry seed.
--
-- This committed file documents the structure of the real, gitignored
-- db/seed/jobs.seed.sql so it is reviewable in the public repo without leaking
-- internal hostnames, IPs, or the operator's actual schedule. The rows below are
-- illustrative placeholders, not real jobs; copy this file to jobs.seed.sql and
-- replace them with the real registry. See db/seed/README.md for apply/verify.
--
-- WHY A SEED (not migration INSERTs): db/migrations/0007-0009 used to INSERT
-- these rows, but they hardcoded an internal deploy host. Per auto-review-6mf.2
-- and docs/superpowers/specs/2026-06-30-jobs-registry-pg.md the ops.jobs registry
-- is now seeded at APPLY TIME from this gitignored file, mirroring the projects
-- registry seed.
--
-- FK ORDERING: ops.job_runs.job_name -> ops.jobs.name means every job needs its
-- ops.jobs row BEFORE it writes its first run-row. Apply order is
-- migrate.sh -> this seed -> first job run (see db/seed/README.md).
--
-- The rows exercise every column and the CHECK (NOT monitored OR
-- expected_interval IS NOT NULL) both ways:
--   * a monitored hourly writer (short expected_interval);
--   * a monitored daily writer (26h = ~24h + grace, the sibling calibration);
--   * a monitored weekly job — NOTE its expected_interval is only the
--     registry/FK sanity bound and the moving-pieces value here; the
--     SCHEDULE-AWARE weekly liveness math lives in the doctor's in-code mechanics
--     map, not in this row (see the design note, decision 1);
--   * two UNMONITORED catalogued pieces (monitored=false, expected_interval
--     NULL) so the moving-pieces dashboard lists the whole stack, coverage gaps
--     included.
-- Placeholder hosts (<runner-host>, <workstation>, <service-host>) stand in for
-- the operator's actual host strings, matching db/README.md's <pg-host>/<cron-host>
-- convention.

INSERT INTO ops.jobs
    (name, host, cadence, writes, monitored, expected_interval)
VALUES
    -- ── monitored: liveness = a fresh ops.job_runs row (or schedule-aware) ──────
    ('example-sync', '<runner-host>', ':05 hourly',
        'example schema (mirror/state) + ops.job_runs',
        true, interval '2 hours'),
    ('example-daily', '<runner-host>', 'nightly (single ordered driver)',
        'example daily row + ops.job_runs',
        true, interval '26 hours'),
    ('example-weekly', '<runner-host>', 'weekly (Mondays)',
        'example weekly row + ops.job_runs',
        true, interval '8 days 2 hours'),
    -- ── catalogued but NOT liveness-monitored (coverage gaps) ───────────────────
    ('example-upstream-push', '<workstation>', 'periodic',
        'upstream feed (no run-row of its own)',
        false, NULL),
    ('example-gateway', '<service-host>', 'always-on',
        'proxy endpoint (no run-row of its own)',
        false, NULL)
ON CONFLICT (name) DO UPDATE SET
    host              = EXCLUDED.host,
    cadence           = EXCLUDED.cadence,
    writes            = EXCLUDED.writes,
    monitored         = EXCLUDED.monitored,
    expected_interval = EXCLUDED.expected_interval;
-- registered_at is stamped once (excluded from the update, like projects.seed's
-- created_at). retired_at is left alone too: retiring a job is a deliberate,
-- separate step (UPDATE ops.jobs SET retired_at = now()) that also drops the row
-- from this seed, so a re-apply never silently revives it — the upsert is
-- add/edit-only, never a delete or a revive, mirroring the projects seed's
-- "upsert never deletes" rule.
