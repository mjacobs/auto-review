-- db/seed/projects.seed.example.sql — sanitized SHAPE of the projects seed.
--
-- This committed file documents the structure of the real, gitignored
-- db/seed/projects.seed.sql so it is reviewable in the public repo without
-- leaking absolute home paths or the operator's actual project inventory. The
-- rows below are illustrative placeholders, not real projects; copy this file
-- to projects.seed.sql and replace them with the curated set. See
-- db/seed/README.md for the apply/verify steps.
--
-- The rows are chosen to exercise every column and constraint variation:
--   * a multi-repo, tracker-backed active project (tracker_workspace set);
--   * a single-repo active project with no vault doc;
--   * a kata-tracked project (the table allows beads | kata | none);
--   * a non-git back-burner project (path present, but activity came from the
--     vault doc, not git);
--   * a repo-less back-burner project (empty repo_paths, vault doc only);
--   * a done project.

INSERT INTO projects.projects
    (name, status, repo_paths, vault_doc, tracker, tracker_workspace, last_activity_at)
VALUES
    -- ── active ────────────────────────────────────────────────────────────────
    ('example-multirepo', 'active',
        ARRAY['<home>/dev/projects/example',
              '<home>/dev/projects/example-mcp'],
        'projects/example-multirepo', 'beads', '<home>/dev/projects/example',
        '2026-06-27'::timestamptz),
    ('example-single', 'active',
        ARRAY['<home>/dev/home/example-single'],
        NULL, 'none', NULL, '2026-06-20'::timestamptz),
    ('example-kata', 'active',
        ARRAY['<home>/dev/projects/example-kata'],
        'projects/example-kata', 'kata', '<home>/dev/projects/example-kata',
        '2026-06-18'::timestamptz),
    -- ── back-burner ───────────────────────────────────────────────────────────
    ('example-nongit', 'back-burner',
        ARRAY['<home>/dev/creative/example-nongit'],
        'projects/back-burner/example-nongit', 'none', NULL,
        '2026-05-30'::timestamptz),
    ('example-repoless', 'back-burner',
        ARRAY[]::text[],
        'projects/back-burner/example-repoless', 'none', NULL,
        '2026-05-15'::timestamptz),
    -- ── done ──────────────────────────────────────────────────────────────────
    ('example-done', 'done',
        ARRAY['<home>/dev/archive/example-done'],
        'projects/back-burner/example-done', 'none', NULL,
        '2026-04-01'::timestamptz)
ON CONFLICT (name) DO UPDATE SET
    status            = EXCLUDED.status,
    repo_paths        = EXCLUDED.repo_paths,
    vault_doc         = EXCLUDED.vault_doc,
    tracker           = EXCLUDED.tracker,
    tracker_workspace = EXCLUDED.tracker_workspace,
    last_activity_at  = EXCLUDED.last_activity_at;
