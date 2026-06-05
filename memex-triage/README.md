# memex-triage

Exactly-once delivery of [`serverless-memex`](https://github.com/mjacobs/serverless-memex)
captures into a single, action-framed Obsidian inbox note for triage.

**Status:** Phase 1 (client scaffold) — fourth `auto-review` sibling. See
[`DESIGN.md`](./DESIGN.md) for the full rationale.

## What it does

`memex-triage sync` walks the cf-memex **change feed** (`GET /thoughts?since=<seq>`)
from a single high-water mark and appends every new capture as a task line to
`inbox/memex.md`:

```markdown
---
last_seq: 4290
last_synced_at: 2026-06-05T09:15:00-07:00
---

# inbox — memex

- [ ] 06-04 14:22 — the retry-loop bug, not the timeout `#debugging` `#agent-review` ^mx-a1b2c3d4
- [ ] 06-05 09:10 — ruff installs faster than poetry `#tooling` `#python` ^mx-0011aabb
```

Delivery is **exactly-once** and **gap-free**: the `seq` is monotonic and never
reused, so a single `last_seq` watermark (stored in the note's own frontmatter)
guarantees nothing is missed or duplicated — even across skipped runs or
backdated captures. Once a line is in the inbox, **you own it**: file it into a
project note, push it into a GTD system, or delete it. The tool only appends.

Unlike the `memex-review` sibling (a daily *recap* — context, not action),
`memex-triage` is meant to run frequently (a `*/5` timer) and accumulate a
persistent, human-drained task list.

## Install

```bash
uv tool install .
```

## Usage

```bash
memex-triage sync                  # poll feed, append new captures, advance watermark
memex-triage sync --dry-run --print   # show what would be appended, write nothing
memex-triage status                # watermark, server head, pending count, inbox size
memex-triage init                  # create inbox at current head (refuses if it exists)
memex-triage init --backfill 0     # create inbox and deliver the whole corpus
```

**First run** (no inbox yet) bootstraps the watermark at the current server
head and delivers nothing — only captures created *after* bootstrap flow in. Use
`init --backfill <seq>` to pull history deliberately.

## Configuration

Set via environment or `.env` in the working directory:

| Variable              | Default                | Description                                |
| --------------------- | ---------------------- | ------------------------------------------ |
| `MEMEX_URL`           | _(required)_           | `serverless-memex` Worker base URL         |
| `MEMEX_CLIENT_ID`     | _(required)_           | Cloudflare Access service-token client id  |
| `MEMEX_CLIENT_SECRET` | _(required)_           | Cloudflare Access service-token secret     |
| `VAULT_PATH`          | `~/vault`              | Obsidian vault root                        |
| `INBOX_PATH`          | `inbox/memex.md`       | Inbox note, relative to the vault (or absolute) |
| `TZ`                  | `America/Los_Angeles`  | Timezone for the `MM-DD HH:MM` stamps      |

## Development

```bash
uv sync --group dev
uv run pytest
uv run memex-triage --help
```

## See also

- [`DESIGN.md`](./DESIGN.md) — why delivery (not decisions), why a seq feed,
  why the watermark lives in frontmatter.
- [`serverless-memex`](https://github.com/mjacobs/serverless-memex) — backing
  store; the `GET /thoughts?since=<seq>` feed it serves (migration 0003).
