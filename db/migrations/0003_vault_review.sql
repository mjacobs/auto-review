-- 0003_vault_review.sql — vault_review schema: daily/weekly digest rows
-- (auto-review-hg6.7: "vault-review migrates to write rows — gets a real
-- store"; today it has no store at all, only the rendered markdown section).
--
-- Shape follows the in-repo precedent of agent_review.daily_reports
-- (agent-review/migrations/001_init.sql): one row per period, keyed by the
-- period label, with a structured payload. Idempotent: safe to re-run.
--
-- events jsonb: the array vault-review computes per window — one element per
-- git-delta event, e.g.
--   {"status": "M", "path": "projects/x/notes.md",
--    "renamed_from": null, "group": "projects/x", "summary": "..."}
-- mirroring gitdelta.collect_events + dossier.group_of/summarize_file.
-- Per-file summaries are stored (not recomputed by the renderer) because
-- summarize_file reads the vault at digest time — the working tree moves on,
-- so the summary is only capturable when the job runs.

CREATE SCHEMA IF NOT EXISTS vault_review;

-- ─── daily digests ────────────────────────────────────────────────────────────
-- window_start/window_end are stored explicitly (vault-review's
-- weekly.day_date_range computes them) so each row is self-describing for the
-- renderer and reproducible without re-deriving TZ/day-boundary logic.
CREATE TABLE IF NOT EXISTS vault_review.daily_digests (
    digest_date  date PRIMARY KEY,
    window_start timestamptz NOT NULL,
    window_end   timestamptz NOT NULL,
    events       jsonb NOT NULL,
    generated_at timestamptz NOT NULL DEFAULT now()
);

-- ─── weekly digests ───────────────────────────────────────────────────────────
-- Keyed by ISO week label, matching vault-review's weekly.parse_week /
-- journal/weekly/YYYY-W##.md convention.
CREATE TABLE IF NOT EXISTS vault_review.weekly_digests (
    week_label   text PRIMARY KEY CHECK (week_label ~ '^[0-9]{4}-W[0-9]{2}$'),
    window_start timestamptz NOT NULL,
    window_end   timestamptz NOT NULL,
    events       jsonb NOT NULL,
    generated_at timestamptz NOT NULL DEFAULT now()
);
