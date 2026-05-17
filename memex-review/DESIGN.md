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
captures ordered DESC by `created_at`. The response includes `content`,
`source`, `summary`, `tags`, and millisecond `created_at` / `updated_at` —
no per-doc round-trip needed.

Auth: Cloudflare Access service token headers.

`collect_thoughts(start, end)` paginates from `before=end_ms` backwards in
pages of 100, filtering to `start_ms <= created_at < end_ms`, stopping when
a page's tail dips below `start_ms`.

## Marker-based idempotency

```
## memex-review — 2026-05-14

_window: 2026-05-14_

### #tag-a (3)
- 14:22 — short summary or content head
- 11:08 — …
- 09:51 — …

### #tag-b (1)
- 17:40 — …

<!-- memex-review:daily=2026-05-14 generated_at=2026-05-15T04:00:00Z -->
```

Section regex matches `## memex-review` through the closing marker
(`re.DOTALL`). `write_daily_section`:

1. Loads frontmatter with `python-frontmatter`.
2. Strips any existing marked section via regex.
3. Appends the new section.
4. Writes back.

Human edits outside the marker survive. Mirrors vault-review's vault.py.

## Grouping

Captures grouped by tag, sorted by count desc then tag name. Captures with
no tag fall under `### (untagged)`. Within a group, items sorted by
`created_at` asc and rendered as `HH:MM — <summary or content-head>`.

If a capture has multiple tags, it appears under each (small dup is fine
for v1; revisit if the noise becomes real).

## File structure

```
src/memex_review/
  config.py    pydantic-settings; MEMEX_URL/_CLIENT_ID/_SECRET, VAULT_PATH, TZ
  client.py    httpx client; collect_thoughts(start, end) -> list[Thought]
  dossier.py   render_dossier(thoughts, date) -> str
  vault.py     read/write/remove for the daily section
  cli.py       click CLI
```

## Out of scope (v1)

- **No weekly recap.** Daily-only matches the project doc's proposed output;
  add `run-weekly` when there's a reason.
- **No LLM.** Deterministic grouping is enough for v1.
- **No git commit/push.** Lives in the openclaw cron wrapper, same as the
  other siblings.
- **No Postgres.** Captures live in cf-memex's D1; we read on demand.

## Related

- [auto-review/auto-review.md](../../../vault/projects/auto-review/auto-review.md)
  (project doc)
- [vault-review/DESIGN.md](../vault-review/DESIGN.md) — pattern this design mirrors
- [serverless-memex/scripts/memex-export.sh](https://github.com/mjacobs/serverless-memex/blob/main/scripts/memex-export.sh)
  — the existing backup script we modeled the API access on
