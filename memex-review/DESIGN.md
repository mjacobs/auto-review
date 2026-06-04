# memex-review — design

## Goals

Generate a deterministic, audit-friendly summary of what was captured into
[cf-memex](https://github.com/mjacobs/serverless-memex) on a given day, and
write it idempotently into the daily check-in note. No LLM, no Postgres,
no side effects beyond the markdown write — just `/thoughts` → markdown.

Sibling of `vault-review` and `agent-review`; same CLI shape, same
marker-based idempotency, same file target.

## Source

`GET $MEMEX_URL/thoughts?limit=100&before=<created_at_ms>` returns up to 100
captures ordered DESC by `created_at`. Each row includes `id`,
`content_preview` (truncated body), `source`, `summary`, `tags`, `metadata`,
and millisecond `created_at` / `updated_at`. The truncated preview is enough
for daily recap lines; we do not hit `GET /thought/:id` per row.

(Discovered via live smoke 2026-05-17: the list endpoint returns
`content_preview`, not full `content`, despite the SQL SELECT in
handlers.ts `listRecent` projecting `content` — the result mapping renames
and truncates.)

Auth: Cloudflare Access service token headers.

`collect_thoughts(start, end)` paginates from `before=end_ms` backwards in
pages of 100, filtering to `start_ms <= created_at < end_ms`, stopping when
a page's tail dips below `start_ms`.

## Framing: inbox, not recap

The daily section is an **inbox surface for triage**, not a topical summary.
Live preview of a 7-day sample (2026-05-17) showed LLM-enriched tags average
4–5 per capture; tag-grouping produced 4–5× bullet duplication and obscured
the chronological flow. Freeform captures are hard to categorize even with
regular use — categorization is the wrong primitive for raw inbox items.

memex-review's job is to *surface* what was captured so it can be processed
later (moved into project notes, discarded, or used to seed a new project).
The triage workflow itself is out of scope for v1 — tracked separately as
`auto-review-qa8`.

## Marker-based idempotency

```
## memex-review — 2026-05-14 — inbox

_window: 2026-05-14 — 3 captures_

- 14:22 — short summary or content head `[#tag-a #tag-b]`
- 17:40 — … `[#tag-b]`
- 19:08 — … `[#tag-a]`

<!-- memex-review:daily=2026-05-14 generated_at=2026-05-15T04:00:00Z -->
```

Section regex matches `## memex-review` through the closing marker
(`re.DOTALL`). `write_daily_section`:

1. Loads frontmatter with `python-frontmatter`.
2. Strips any existing marked section via regex.
3. Appends the new section.
4. Writes back.

Human edits outside the marker survive. Mirrors vault-review's vault.py.

## Layout

Flat, chronological (oldest first). Each capture is one bullet:

    - HH:MM — <summary or first-line of content_preview> `[#tag-1 #tag-2 …]`

Tags render as inline chips, not section headers. Captures with no tags
omit the chip group entirely. HH:MM is the capture's `created_at` rendered
in the configured `TZ`. Line text prefers `summary` (LLM-enriched) and
falls back to the first non-empty line of `content_preview`.

Empty windows render `_no captures in window_` instead of a bullet list.

## Processing model

The inbox is **everything captured since the cursor**. Processing a capture
means looking at it and deciding what to do with it — write into a project
note, ignore, or drop into a backlog vault note. The system doesn't care
which outcome; the only durable state change is the cursor advance.

**Strict linear consumption.** Captures are consumed in chronological order.
There is no per-item state, no deferred set, no skip list. If a capture
can't be decided right now, it goes into a backlog vault note like any
other thought, and the cursor advances past it. The backlog is just
notebook content, not a system feature.

**State location.** `~/vault/state/memex-review.yaml` — vault-side so it
syncs across machines via the vault repo and stays cleanly separate from
cf-memex's data model.

**State shape:**

```yaml
cursor: 2026-05-17T23:59:59-07:00   # ISO-8601 with tz
```

**Bootstrap.** On first run with no cursor file, `load_cursor` returns
start-of-today local for `memex-review cursor` but does *not* persist it.
For `run <date>`, the CLI uses start-of-requested-date as the temporary
cursor until a real cursor file exists. This keeps a first manual
`run yesterday` useful while preserving explicit cursor advancement as
the durable processing signal.

**Filter site.** The cursor is applied between fetch and render in the
CLI. `client.collect_thoughts` stays cursor-unaware (pure data fetch);
the CLI loads the cursor and drops pre-cursor items before passing to
`render_dossier`. The rendered count and `_no captures in window_`
placeholder reflect visible (post-filter) counts.

**Interaction.** Inline triage in Obsidian — read the inbox section in
the check-in note, manually cut/paste into project notes or dump into a
backlog note, then commit the advance with `memex-review process`.

## File structure

```
src/memex_review/
  config.py    pydantic-settings; MEMEX_URL/_CLIENT_ID/_SECRET, VAULT_PATH, TZ
  client.py    httpx client; collect_thoughts(start, end) -> list[Thought]
  cursor.py    cursor load/save + filter_visible(thoughts, cursor)
  dossier.py   render_dossier(thoughts, date) -> str
  vault.py     read/write/remove for the daily section
  cli.py       click CLI (run/today/yesterday/show/reset/process/cursor)
```

## Out of scope (v1)

- **No per-item state.** The cursor is a single monotone watermark; there
  is no "defer" or "skip" set. Indecision goes into a backlog note via
  convention.
- **No multi-cursor / multi-source generalization.** The other auto-review
  siblings keep their own model.
- **No GUI / Obsidian plugin.** Inline triage in the check-in note is fine.
- **No weekly recap.** Daily-only matches the project doc's proposed output;
  add `run-weekly` when there's a reason.
- **No LLM.** Deterministic grouping is enough for v1.
- **No git commit/push.** Lives in the cron wrapper, same as the
  other siblings.
- **No Postgres.** Captures live in cf-memex's D1; we read on demand.

## Related

- [auto-review/auto-review.md](../../../vault/projects/auto-review/auto-review.md)
  (project doc)
- [vault-review/DESIGN.md](../vault-review/DESIGN.md) — pattern this design mirrors
- [serverless-memex/scripts/memex-export.sh](https://github.com/mjacobs/serverless-memex/blob/main/scripts/memex-export.sh)
  — the existing backup script we modeled the API access on
