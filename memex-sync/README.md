# memex-sync

Periodic D1 → Postgres sync: pulls new captures from the
[serverless-memex](https://github.com/mjacobs/serverless-memex)
`GET /thoughts?since=<seq>` change feed and upserts them into the `memex`
schema on the shared Postgres instance — the canonical capture store that the
check-in renderer and the triage surface read (`auto-review-hg6.3`; schema in
[`../db/migrations/0002_memex.sql`](../db/migrations/0002_memex.sql)).

A sibling of `agent-review` / `vault-review` / `memex-review` /
`memex-triage`, but unlike all of them it **touches no files**: no vault, no
markdown, no git. Rows are the product.

## What one run does

```
memex.sync_state ──read──▶ watermark (last_seq for consumer 'memex_sync')
        feed     ──GET───▶ /thoughts?since=<watermark>   (paged by 100)
   ┌─ one transaction ────────────────────────────────────────────────┐
   │  memex.captures        INSERT ... ON CONFLICT (id) DO UPDATE     │
   │  memex.capture_triage  INSERT (state='untriaged') ... DO NOTHING │
   │  memex.sync_state      watermark -> max(seq) of the batch        │
   └──────────────────────────────────────────────────────────────────┘
   ops.job_runs  ──separate connection──▶ one row per run, ok|error
```

* **Exactly-once by `seq`.** The feed's monotonic, never-reused sequence
  (see [`../memex-triage/DESIGN.md`](../memex-triage/DESIGN.md)) is walked
  from a single high-water mark. Because rows and watermark commit in one
  transaction, a crash mid-batch re-fetches cleanly next run; upserts keyed
  on capture `id` make any re-delivery (e.g. after a deliberate watermark
  reset) idempotent.
* **Sync never touches triage state.** It seeds an `'untriaged'` row per new
  capture via `ON CONFLICT DO NOTHING`; flipping state is the triage
  surface's job, and the `memex_sync` role's grants (INSERT but no UPDATE on
  `capture_triage` — `0005_roles.sql`) enforce the boundary.
* **Every run leaves evidence.** An idle run writes no capture rows but still
  inserts an `ops.job_runs` row (the doctor's liveness signal); a failed run
  records `status='error'` on a separate connection, so the rollback of the
  data transaction can't erase it.
* **Independent consumer.** The desktop `memex-triage` timer reads the same
  feed with its own watermark (in its inbox note's frontmatter). The two
  never interact; `memex.sync_state` is keyed by consumer name for exactly
  this reason.

## Bootstrap

First run with no `memex.sync_state` row starts from **seq 0 — a full
historical backfill**. That is the documented default and the opposite of
memex-triage's start-at-head: the canonical store wants all history, the
human triage inbox does not. To start elsewhere, pass `--since <seq>`
(e.g. the current server head to skip history); the watermark then advances
to at least that value even if the feed returns nothing.

## Known limitation: preview, not full content

The feed serves `content_preview` (capped), falling back to `content` when
the worker provides it; `memex.captures.content` stores **whatever the feed
delivers**. Whether the worker should expose full content to this consumer is
an open question tracked in [`../db/README.md`](../db/README.md) (open
question 2) — it is a serverless-memex change, deliberately not made here.
The feed also has no tombstones, so D1 deletions never propagate to the
mirror (open question 3).

## CLI

```
memex-sync                      # = memex-sync sync
memex-sync sync                 # pull new captures, advance watermark, record run
memex-sync sync --dry-run --print   # fetch + show what would land; writes nothing
memex-sync sync --since 0      # re-walk from seq 0 (idempotent re-delivery)
memex-sync status               # watermark vs server head, mirror row counts
```

`--dry-run` writes nothing at all — no captures, no watermark, and no
`job_runs` row.

## Config

Via env / `.env` (pydantic-settings; see [`.env.example`](./.env.example)):

| var | required | meaning |
|---|---|---|
| `PG_DSN` | yes | DSN for the `memex_sync` role; password optional if `~/.pgpass` (or repo-local `.pgpass`) has an entry |
| `MEMEX_URL` / `MEMEX_CLIENT_ID` / `MEMEX_CLIENT_SECRET` | yes | cf-memex worker URL + CF Access service token (same creds as the siblings) |
| `MEMEX_SYNC_CONSUMER` | no | `memex.sync_state` key (default `memex_sync`) |
| `MEMEX_SYNC_JOB_NAME` | no | `ops.job_runs.job_name` (default `memex-sync`; must be registered in `ops.jobs` — FK) |
| `MEMEX_SYNC_HOST` | no | `ops.job_runs.host` (default: hostname) |

## Development

```bash
cd memex-sync
uv sync
uv run pytest
uv run ruff check src tests
```

Tests run against a fake feed and an in-memory fake of the PG layer — no
live database or network needed. Deployment: see
[`deploy/README.md`](./deploy/README.md) (role password provisioning,
`ops.jobs` registration, cron line).
