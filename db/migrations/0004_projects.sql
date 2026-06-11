-- 0004_projects.sql — projects schema: the explicit, curated, machine-
-- suggested project registry (auto-review-8cw.1).
--
-- Human-curated (registry membership is a human decision), machine-suggested
-- (the change-inference detector proposes candidates — 8cw.5). Not exclusive:
-- non-curated activity still flows through reviews; the registry adds
-- persistent context, it doesn't gate. Idempotent: safe to re-run.

CREATE SCHEMA IF NOT EXISTS projects;

-- ─── registry ─────────────────────────────────────────────────────────────────
-- Columns are exactly the 8cw.1 spec: id, name, status (active/back-burner/
-- done), repo path(s), vault doc link, tracker (beads|kata|none — one or the
-- other, never both) + tracker workspace location, created, last-activity.
--   repo_paths       — plural per spec ("repo path(s)"); some projects span
--                      more than one checkout.
--   vault_doc        — vault-relative path to the project doc (the
--                      ~/vault/projects/* convention).
--   last_activity_at — machine-updated by the detector/reviews; the staleness
--                      signal for the open-loop view (8cw.4).
CREATE TABLE IF NOT EXISTS projects.projects (
    id                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name              text NOT NULL UNIQUE,
    status            text NOT NULL DEFAULT 'active'
                           CHECK (status IN ('active', 'back-burner', 'done')),
    repo_paths        text[] NOT NULL DEFAULT '{}',
    vault_doc         text,
    tracker           text NOT NULL DEFAULT 'none'
                           CHECK (tracker IN ('beads', 'kata', 'none')),
    tracker_workspace text,
    created_at        timestamptz NOT NULL DEFAULT now(),
    last_activity_at  timestamptz,
    -- a workspace location only makes sense when a tracker is set
    CHECK (tracker <> 'none' OR tracker_workspace IS NULL)
);

-- ─── capture -> project association: deferred ─────────────────────────────────
-- The association table (memex.captures -> projects.projects, with
-- suggested-by-machine / confirmed-by-human state) is auto-review-8cw.2 and
-- depends on the triage surface design (hg6.9). It gets its own migration
-- when that work lands; nothing here speculates on its shape.

-- ─── seeding ──────────────────────────────────────────────────────────────────
-- Intentionally no INSERTs. 8cw.1 seeds from ~/vault/projects/* + the ~/dev
-- inventory — local-machine knowledge that belongs in the seeding step at
-- apply time, not in a public migration file.
