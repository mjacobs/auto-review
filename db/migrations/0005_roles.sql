-- 0005_roles.sql — least-privilege roles + grants for the composition layer
-- (auto-review-hg6.2: "Access: roles/creds for the cron-host jobs").
--
-- One role per writing job; the doctor and the renderer are SELECT-only
-- across schemas; the triage CLI writes triage state and the projects
-- registry, nothing else. No role can do DDL — migrations run as the
-- admin/owner. NO passwords here: roles are created LOGIN with no password;
-- passwords are set out-of-band (db/set-role-passwords.sh from env, or
-- \password in psql). See db/README.md "Role model".
--
-- Naming: vault_review_job (not vault_review) so the role does not shadow the
-- vault_review SCHEMA name in grants/pgpass entries and \du/\dn listings.
-- (Roles and schemas are separate PG namespaces — the live agent_review
-- role/schema pair proves it works — but new names need not collide.)
--
-- The agent_review role ALREADY EXISTS on the live instance (verified
-- 2026-06-11: LOGIN, DML on agent_review.*, SELECT on agentsview.* — see
-- db/reference/agent_review.sql). The DO block below creates roles only when
-- missing and never alters existing ones; the ONLY thing this migration adds
-- to agent_review is INSERT on ops.job_runs (+ the USAGE on schema ops that
-- INSERT requires).
-- Idempotent: CREATE ROLE is guarded; GRANT is naturally re-runnable.

-- ─── role creation (create-if-missing, never alter) ───────────────────────────
DO $$
DECLARE
    r text;
BEGIN
    FOREACH r IN ARRAY ARRAY[
        'memex_sync',          -- D1 -> PG capture sync job (hg6.3)
        'memex_review',        -- memex-review daily job (hg6.4)
        'vault_review_job',    -- vault-review daily/weekly job (hg6.7)
        'agent_review',        -- agent-review daily job (pre-existing live role)
        'auto_review_doctor',  -- doctor (hg6.8): read-only + records its runs
        'checkin_renderer',    -- check-in renderer (hg6.5), strictly read-only
        'memex_triage'         -- triage CLI/MCP surface (hg6.9)
    ] LOOP
        IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
            EXECUTE format('CREATE ROLE %I LOGIN', r);
        END IF;
    END LOOP;
END
$$;

-- ─── ops: every periodic job appends its run rows ─────────────────────────────
-- job_runs is append-only: job roles get INSERT and nothing else (no SELECT,
-- no UPDATE — history is immutable; reading it is the doctor/renderer's job).
-- The doctor is itself a monitored periodic job, so it records runs too.
GRANT USAGE ON SCHEMA ops
    TO memex_sync, memex_review, vault_review_job, agent_review,
       auto_review_doctor, checkin_renderer;

GRANT INSERT ON ops.job_runs
    TO memex_sync, memex_review, vault_review_job, agent_review,
       auto_review_doctor;

-- liveness/cost queries (doctor) and the health/moving-pieces views (renderer)
GRANT SELECT ON ops.jobs, ops.job_runs
    TO auto_review_doctor, checkin_renderer;
-- (ops.schema_migrations stays admin-only: nothing else needs it.)

-- ─── memex ────────────────────────────────────────────────────────────────────
GRANT USAGE ON SCHEMA memex
    TO memex_sync, memex_review, memex_triage,
       auto_review_doctor, checkin_renderer;

-- sync job: upserts captures, seeds default triage rows (ON CONFLICT DO
-- NOTHING — hence INSERT but no UPDATE on capture_triage), owns the watermark
GRANT SELECT, INSERT, UPDATE ON memex.captures       TO memex_sync;
GRANT SELECT, INSERT         ON memex.capture_triage TO memex_sync;
GRANT SELECT, INSERT, UPDATE ON memex.sync_state     TO memex_sync;

-- readers: memex-review builds the daily inbox section; doctor/renderer read
GRANT SELECT ON memex.captures, memex.capture_triage, memex.sync_state
    TO memex_review, auto_review_doctor, checkin_renderer;

-- triage CLI: flips triage state; cannot touch the captures mirror
GRANT SELECT ON memex.captures, memex.capture_triage      TO memex_triage;
GRANT UPDATE (state, updated_at) ON memex.capture_triage  TO memex_triage;

-- ─── vault_review ─────────────────────────────────────────────────────────────
GRANT USAGE ON SCHEMA vault_review
    TO vault_review_job, auto_review_doctor, checkin_renderer;

GRANT SELECT, INSERT, UPDATE
    ON vault_review.daily_digests, vault_review.weekly_digests
    TO vault_review_job;

GRANT SELECT
    ON vault_review.daily_digests, vault_review.weekly_digests
    TO auto_review_doctor, checkin_renderer;

-- ─── projects ─────────────────────────────────────────────────────────────────
-- The triage surface is where capture->project association gets confirmed
-- (8cw.2 rides hg6.9), so the triage CLI curates the registry: read/write but
-- no DELETE — retirement is status = 'done', so registry history survives.
GRANT USAGE ON SCHEMA projects
    TO memex_triage, auto_review_doctor, checkin_renderer;

GRANT SELECT, INSERT, UPDATE ON projects.projects TO memex_triage;
GRANT SELECT                 ON projects.projects TO auto_review_doctor,
                                                     checkin_renderer;

-- ─── agent_review + agentsview (pre-existing schemas; read-only consumers) ────
-- Neither schema is created by this directory (agent_review comes from
-- agent-review/migrations/001_init.sql; agentsview is the upstream session
-- store). The doctor and the renderer read both: agent_review.daily_reports
-- feeds the check-in's report section and its est_cost_usd feeds cost views;
-- agentsview is the upstream the doctor sanity-checks freshness against.
-- Guarded so this migration also applies cleanly to an empty scratch DB.
-- NOTE: GRANT ... ON ALL TABLES is point-in-time — tables added to these
-- schemas later need a re-run or their own grant (see README open questions).
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'agent_review') THEN
        GRANT USAGE ON SCHEMA agent_review
            TO auto_review_doctor, checkin_renderer;
        GRANT SELECT ON ALL TABLES IN SCHEMA agent_review
            TO auto_review_doctor, checkin_renderer;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'agentsview') THEN
        GRANT USAGE ON SCHEMA agentsview
            TO auto_review_doctor, checkin_renderer;
        GRANT SELECT ON ALL TABLES IN SCHEMA agentsview
            TO auto_review_doctor, checkin_renderer;
    END IF;
END
$$;

-- ─── future tables ────────────────────────────────────────────────────────────
-- Deliberately no ALTER DEFAULT PRIVILEGES: every new table arrives via a
-- migration, and that migration carries its own explicit grants. Boring and
-- auditable beats implicit.
