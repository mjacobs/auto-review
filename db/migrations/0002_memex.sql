-- 0002_memex.sql — memex schema: PG mirror of cf-memex captures, PG-owned
-- triage state, and the sync watermark (auto-review-hg6.3).
--
-- Two write paths, deliberately split into two tables:
--   memex.captures        — written ONLY by the D1 -> PG sync job (memex_sync);
--                           a mirror of serverless-memex's documents feed.
--   memex.capture_triage  — written ONLY by the triage surface (hg6.9);
--                           PG-owned state that has no D1 counterpart.
-- The split keeps "serverless-memex is captures-only; processing state lives
-- on our side" (AGENTS.md) intact in the new substrate, and lets each role
-- carry the narrowest possible grants (see 0005_roles.sql).
-- Idempotent: safe to re-run.

CREATE SCHEMA IF NOT EXISTS memex;

-- ─── captures (mirror of the D1 change feed) ──────────────────────────────────
-- Column shape mirrors memex-triage's Thought dataclass / the
-- GET /thoughts?since=<seq> feed (memex-triage/src/memex_triage/client.py):
-- id, seq, content, summary, tags, source, created_at, updated_at.
--   id    — D1 documents.id, a TEXT uuid upstream; kept text to mirror the
--           source of truth rather than re-typing it.
--   seq   — the never-reused monotonic counter from serverless-memex
--           migration 0003 (see memex-triage/DESIGN.md). UNIQUE both enforces
--           mirror integrity and serves the watermark/ordering queries.
CREATE TABLE IF NOT EXISTS memex.captures (
    id         text PRIMARY KEY,
    seq        bigint NOT NULL UNIQUE,
    content    text NOT NULL,                 -- feed delivers content_preview or content
    summary    text,                          -- LLM enrichment; nullable upstream
    tags       text[] NOT NULL DEFAULT '{}',
    source     text,                          -- capture source; nullable upstream
    created_at timestamptz NOT NULL,          -- from D1 created_at (ms epoch upstream)
    updated_at timestamptz NOT NULL,          -- from D1 updated_at (ms epoch upstream)
    synced_at  timestamptz NOT NULL DEFAULT now()
);

-- daily-window queries (memex-review's "captures for day X" inbox section)
CREATE INDEX IF NOT EXISTS idx_captures_created_at
    ON memex.captures (created_at);

-- ─── triage state (PG-owned; no D1 counterpart) ───────────────────────────────
-- Replaces checkbox-lines-with-^mx- block IDs in inbox/memex.md. The sync job
-- inserts a default 'untriaged' row per capture (ON CONFLICT DO NOTHING); the
-- triage surface (hg6.9) flips state. The inbox projection is
--   ... WHERE state = 'untriaged' ORDER BY c.seq
-- States per hg6.3: untriaged / filed / discarded.
-- The project-association FK (capture -> projects.projects) is deferred to its
-- own migration under auto-review-8cw.2 — see 0004_projects.sql.
CREATE TABLE IF NOT EXISTS memex.capture_triage (
    capture_id text PRIMARY KEY REFERENCES memex.captures(id) ON DELETE CASCADE,
    state      text NOT NULL DEFAULT 'untriaged'
                    CHECK (state IN ('untriaged', 'filed', 'discarded')),
    updated_at timestamptz NOT NULL DEFAULT now()
);

-- the inbox projection's scan
CREATE INDEX IF NOT EXISTS idx_capture_triage_untriaged
    ON memex.capture_triage (capture_id) WHERE state = 'untriaged';

-- ─── sync watermark ───────────────────────────────────────────────────────────
-- The seq high-water mark, moved out of inbox/memex.md frontmatter (hg6.3:
-- "the watermark just lives in a PG row"). Keyed by consumer name because the
-- desktop memex-triage timer and the D1 -> PG sync job are independent
-- consumers of the same feed, each with its own watermark. A separate table
-- (rather than MAX(seq) over captures) preserves the bootstrap-at-head case:
-- a fresh consumer can start at the server head without backfilling rows
-- (memex-triage's init_inbox/server_head semantics).
CREATE TABLE IF NOT EXISTS memex.sync_state (
    consumer   text PRIMARY KEY,
    last_seq   bigint NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
);
