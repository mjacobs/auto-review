# memex-triage — design

## Goal

Deliver **every** `serverless-memex` capture into a single, action-framed
vault inbox note (`inbox.md`), **exactly once**, with a hard completeness
guarantee — so the inbox is a trustworthy list of things that still need
triage. Once a capture lands in `inbox.md`, the human owns it: file it into
a project note, push it into a GTD system, or delete the line. The tool's
job ends at delivery.

This is a fourth sibling alongside `agent-review`, `vault-review`, and
`memex-review`, but it deliberately breaks one assumption the others share:
it is **not** a daily batch recap. It polls continuously and appends to a
persistent, human-drained note rather than regenerating a dated section.

## Framing: triage surface vs. recap surface

`memex-review` already exists and **stays exactly as it is**. The two tools
read the same source but serve opposite purposes:

| | `memex-review` (exists) | `memex-triage` (this) |
|---|---|---|
| Cadence | daily batch (cron, ~04:00) | continuous poll (`*/5`) |
| Window | fixed 24 h | everything since last seen |
| Output | dated section in the check-in note | append to one rolling `inbox.md` |
| Idempotency | strip-and-replace by date marker | exactly-once by `seq` watermark |
| Framing | **context** — "what happened that day" | **action** — "what still needs triage" |
| Lifecycle | regenerated; ephemeral | drained by hand; persistent |
| Requires action? | no | yes (at least: triage) |

Keeping them separate is the point. The daily recap is allowed to repeat,
re-render, and disappear. The triage inbox must never drop a capture and
must never re-surface one the human already dealt with.

## The completeness problem

`memex-review` paginates by `created_at` against a wall-clock cursor. That
is fine for a "what happened today" recap, but it has two silent failure
modes that are unacceptable for a triage inbox:

1. **Skipped/late runs.** If a daily run is missed, captures in that window
   are never surfaced — the cursor has already moved past their day.
2. **Out-of-order arrival.** A capture whose `created_at` predates the
   cursor (backdated import, clock skew, late write) is filtered out and
   lost forever.

Time is the wrong axis. The fix is a **monotonic per-row sequence** the
client tracks as a single high-water mark.

## Server contract: a `seq` change feed (serverless-memex)

> [!IMPORTANT]
> Cross-repo change. The server side lives in
> [`serverless-memex`](https://github.com/mjacobs/serverless-memex) and must
> ship (migration + Worker deploy) before the client is useful. Flag the
> boundary and confirm the D1 migration before running it.

### Schema (`migrations/0003_seq.sql`)

`documents.id` is a UUID, so it is never reused — but a `seq` minted as
`MAX(seq)+1` **would** be reused if the current-max row is later deleted,
silently skipping the next insert for any client already at that watermark.
So `seq` must come from a **never-reused counter**, AUTOINCREMENT-style:
deletes may leave gaps (fine for a watermark), but a value is never handed
out twice (fatal otherwise).

```sql
CREATE TABLE IF NOT EXISTS counters (
  name  TEXT PRIMARY KEY,
  value INTEGER NOT NULL
);
INSERT OR IGNORE INTO counters (name, value) VALUES ('doc_seq', 0);

ALTER TABLE documents ADD COLUMN seq INTEGER;

-- Backfill existing rows in insert order (created_at, rowid as tiebreak).
UPDATE documents
SET seq = (
  SELECT COUNT(*) FROM documents AS d2
  WHERE d2.created_at < documents.created_at
     OR (d2.created_at = documents.created_at AND d2.rowid <= documents.rowid)
);

UPDATE counters SET value = (SELECT COALESCE(MAX(seq), 0) FROM documents)
WHERE name = 'doc_seq';

CREATE UNIQUE INDEX IF NOT EXISTS idx_documents_seq ON documents (seq);
```

### Mint `seq` atomically on insert (`handlers.ts: capture`)

D1 serializes writes within a database, and `DB.batch([...])` runs as one
implicit transaction. Increment the counter and read it back inside the
same `INSERT ... SELECT` so the assignment is atomic:

```ts
await env.DB.batch([
  env.DB.prepare("UPDATE counters SET value = value + 1 WHERE name = 'doc_seq'"),
  env.DB.prepare(
    `INSERT INTO documents
       (id, content, content_hash, source, metadata, summary, tags, created_at, updated_at, seq)
     SELECT ?, ?, ?, ?, ?, ?, ?, ?, ?, value FROM counters WHERE name = 'doc_seq'`,
  ).bind(docId, content, hash, source, metaStr, summary, tagsStr, now, now),
]);
```

The existing dedupe path (re-capture of an identical `content_hash` only
bumps `updated_at`) is unchanged: no new row, no new `seq`, so the feed
never re-emits a duplicate capture. Edits that change content are out of
scope for re-delivery in v1 (see Out of scope).

### Read: `GET /thoughts?since=<seq>`

Extend the existing `/thoughts` handler with a `since` parameter
(`before` stays for the export script and `memex-review` — fully backwards
compatible):

```sql
SELECT id, content_preview, source, summary, tags, metadata, created_at, updated_at, seq
FROM documents
WHERE seq > ?
ORDER BY seq ASC
LIMIT ?;
```

Same Cloudflare Access service-token auth as today. The response includes
`seq` on each row. An idle feed returns `[]` — a single indexed read, no
Workers AI, no Vectorize.

## Client model (memex-triage)

A single high-water mark, advanced only when new data is observed.

**State lives in the inbox note's own frontmatter** — `inbox/memex.md`:

```yaml
---
last_seq: 4287          # highest seq delivered to this note
last_synced_at: 2026-06-05T09:12:00-07:00   # debug only
---
```

Co-locating the watermark with the note it guards is deliberate: appending
new task lines and advancing `last_seq` become a **single atomic write of one
file** (read frontmatter+body, append lines, bump `last_seq`, write back — the
siblings already do this with `python-frontmatter`). Either the whole update
lands or none of it does; there is no two-file crash window. The one tradeoff:
the watermark is tied to this file's integrity — if you rotate/replace
`inbox/memex.md`, carry the `last_seq` property over (or re-`init`), else
delivery restarts from that point.

**Why just a watermark, not a per-id ledger.** Because `seq` is monotonic,
"is there anything new?" reduces to `server_max_seq > last_seq`. There is no
need to record every id seen, and **no need to record polls** — an idle poll
writes nothing. Write/commit cadence collapses from "every 5 min" to "once
per batch of new captures."

**Sync algorithm (`memex-triage sync`):**

1. Read `inbox/memex.md` → frontmatter `last_seq` (bootstrap: see below) + body.
2. Page `GET /thoughts?since=<last_seq>` until a short page; collect new rows
   ordered by `seq` ASC.
3. If none → exit without touching the file (idle poll = no-op).
4. Append one task line per row to the body (oldest first), set frontmatter
   `last_seq = max(seq)` of the batch, and write the file back **once**.

**Single atomic write removes the ordering hazard.** Because the appended
lines and the new `last_seq` are written together in one file, a crash either
loses the whole batch (re-fetched cleanly next run) or commits it whole —
never a half-state where the watermark advanced past un-appended lines. Each
line still carries the source id, so a stray duplicate (e.g. from a partial
git push, not a partial write) is identifiable and hand-deletable.

## Inbox note format

One persistent file, `inbox/memex.md` (configurable via `INBOX_PATH`; the
`inbox/` dir is where other triage-bound content lands too).
**Append-only from the tool's side** — it adds task lines and never sorts,
reorganizes, or rewrites the body, so any GTD layer added on top can't fight
it. Lines are Markdown task checkboxes so the Obsidian Tasks/GTD plugins can
query them later with zero changes here:

```markdown
---
last_seq: 4290
last_synced_at: 2026-06-05T09:15:00-07:00
---

# inbox — memex

Captures awaiting triage. Delete a line once it's filed. Tool only appends
below; it owns the `last_seq` property.

- [ ] 06-04 14:22 — the retry-loop bug, not the timeout `#debugging` `#agent-review` ^mx-a1b2c3d4
- [ ] 06-04 17:40 — weekly retro could pull from agent-review digests `#meta` ^mx-9f8e7d6c
- [ ] 06-05 09:10 — ruff installs faster than poetry `#tooling` `#python` ^mx-0011aabb
```

- **Checkbox** (`- [ ]`) — the future-proof GTD primitive.
- **`MM-DD HH:MM`** — capture `created_at` in `TZ`; date shown because the
  inbox spans multiple days.
- **Text** — prefers `summary`, falls back to first non-empty line of
  `content_preview` (same rule as `memex-review`).
- **Tag chips** — inline, from enriched `tags`; omitted when empty.
- **`^mx-<id8>` block ref** — stable Obsidian anchor + the source-thought
  backlink. Full id recoverable via memex if needed.

A line's **absence** means "done." The tool never re-adds it because
`last_seq` is past it — independent of whatever the human did to the body.

## Run model

- **Where:** a `systemd --user` `*/5` timer on the **Fedora desktop** — the
  same machine where triage editing happens. The desktop is therefore the
  **sole writer** of `inbox/memex.md` (the watermark rides in its
  frontmatter), which is how the two-writer problem is avoided.
  (`memex-review` keeps running on the LXC runner, writing *different* files,
  so the existing pipeline is untouched.)
- **`Persistent=true`** so a missed timer fires on wake; one
  `since=last_seq` fetch catches up everything missed while asleep. Inbox is
  stale only while the desktop is off — acceptable, since triage only
  happens at the desktop anyway.
- **Git stays in a thin wrapper, not the Python tool** (sibling convention).
  The timer runs `run-memex-triage.sh`, which calls `memex-triage sync` then
  commits + pushes **only if `git status` is dirty** — i.e. only when a batch
  was appended. Idle polls produce no commit. `git pull --rebase` before
  push, retry on rejection, to coexist with the LXC runner's daily commits.
- **Cloudflare cost is a non-issue:** ~288 polls/day, each a single indexed
  D1 read usually returning `[]`. Far under any Workers quota; no Workers AI
  or Vectorize touched.

## Bootstrap

First run with no `last_seq` (no `inbox/memex.md`, or the file lacks the
property):

- **Default — start at head.** Fetch the current `server_max_seq`, create
  `inbox/memex.md` with `last_seq` set to it and an empty task list. Avoids
  dumping the entire historical corpus into the triage list on day one.
- **`memex-triage init --backfill <seq|date>`** — opt-in: set `last_seq`
  lower to pull history into the inbox deliberately.

## CLI shape

Minimal; mirrors sibling idioms (`--dry-run`, `--print`).

```
memex-triage sync                 # poll, append new, advance watermark (timer target)
memex-triage sync --dry-run --print
memex-triage status               # last_seq, server max seq, # pending, inbox line count
memex-triage init [--backfill <seq|date>]   # bootstrap watermark; refuses if state exists
```

## File structure

Mirrors `vault-review/`:

```
memex-triage/
  pyproject.toml
  src/memex_triage/
    config.py     pydantic-settings; MEMEX_URL/_CLIENT_ID/_SECRET, VAULT_PATH, INBOX_PATH=inbox/memex.md, TZ
    client.py     httpx; fetch_since(last_seq) -> list[Thought] (paginated)
    inbox.py      python-frontmatter read/append/write; last_seq in frontmatter; render_line(thought)
    cli.py        click verbs: sync, status, init
  tests/
  deploy/
    run-memex-triage.sh           # sync + conditional git commit/push
    memex-triage.timer / .service # systemd --user units (*/5, Persistent)
    README.md
  DESIGN.md
  README.md
```

## Execution plan

**Phase 0 — server change (`serverless-memex`).** Add
`migrations/0003_seq.sql` (counter, `seq` column, backfill, unique index).
Patch `capture` to mint `seq` via the atomic `batch`. Add `since` to the
`/thoughts` handler. Tests for: monotonic-no-reuse across a delete, feed
ordering, `since` boundary, backfill correctness. Deploy Worker + run D1
migration (confirm before running). *Gate: the rest depends on this.*

**Phase 1 — client scaffold.** Copy `vault-review/` layout. `config.py`
(+`INBOX_PATH`), `client.fetch_since`, `watermark.py`, `inbox.py`
(`render_line` + append-only writer), `cli.py` (`sync`/`status`/`init`).

**Phase 2 — correctness.** Atomic frontmatter+body write (`last_seq` advances
with the append); bootstrap (start-at-head + `--backfill`); `--dry-run/--print`;
tests for exactly-once, empty-feed no-op, frontmatter round-trip, line rendering.

**Phase 3 — deploy.** `run-memex-triage.sh` (sync + dirty-only commit/push
with rebase+retry); `systemd --user` `.timer`/`.service` (`*/5`,
`Persistent=true`) on the desktop. Verify single-writer; verify catch-up
after sleep.

**Phase 4 — later (not now).** GTD plugin wiring; richer per-item actions;
content-edit re-delivery; archival/rotation of `inbox.md`.

## Out of scope (v1)

- **No decision ledger / `--apply` / `promote` verb.** Delivery only; the
  human manages items in Obsidian after they land.
- **No LLM.** Deterministic, like the other siblings. No auto-classify, no
  suggested targets.
- **No server-side triage state.** `serverless-memex` stays ignorant of
  downstream processing; it only gains a read-completeness mechanism (`seq`),
  not a "triaged" flag.
- **No content-edit re-delivery.** The feed surfaces new captures by `seq`;
  edits to an existing capture do not re-appear in the inbox.
- **No inbox rotation/size management.** The note grows until the human
  drains it; a runaway inbox is a signal, not a tool concern.
- **No multi-writer / multi-vault decoupling.** Single desktop writer is the
  v1 assumption. The deeper "one vault is the coupling" question is a future
  hurdle, explicitly not designed for here.
- **No change to `memex-review`.** The daily recap is untouched.

## Related

- [`memex-review/DESIGN.md`](../memex-review/DESIGN.md) — the daily-recap
  sibling and its wall-clock cursor (the model this tool deliberately drops).
- [`vault-review/DESIGN.md`](../vault-review/DESIGN.md) — layout/idempotency
  pattern this mirrors.
- [`AGENTS.md`](../AGENTS.md) — sibling shape, deploy + side-effect rules.
- [`serverless-memex`](https://github.com/mjacobs/serverless-memex) — backing
  store; Phase 0 lands here.
