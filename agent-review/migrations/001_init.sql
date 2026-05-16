-- agent-review schema. Lives alongside the read-only agentsview schema.
-- Idempotent: safe to re-run.

CREATE SCHEMA IF NOT EXISTS agent_review;

CREATE TABLE IF NOT EXISTS agent_review.session_digests (
    session_id    text PRIMARY KEY
                       REFERENCES agentsview.sessions(id) ON DELETE CASCADE,
    data_version  integer NOT NULL,
    model         text    NOT NULL,
    prompt_tokens integer NOT NULL,
    output_tokens integer NOT NULL,
    cached_tokens integer NOT NULL DEFAULT 0,
    digest        jsonb   NOT NULL,
    generated_at  timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_session_digests_generated_at
    ON agent_review.session_digests(generated_at);

CREATE TABLE IF NOT EXISTS agent_review.daily_reports (
    report_date       date PRIMARY KEY,
    generated_at      timestamptz NOT NULL DEFAULT now(),
    model             text    NOT NULL,
    sessions_included text[]  NOT NULL,
    narrative_md      text    NOT NULL,
    stats             jsonb   NOT NULL,
    prompt_tokens     integer NOT NULL,
    output_tokens     integer NOT NULL,
    cached_tokens     integer NOT NULL DEFAULT 0,
    est_cost_usd      numeric(10, 4) NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_daily_reports_generated_at
    ON agent_review.daily_reports(generated_at);
