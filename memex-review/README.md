# memex-review

Daily inbox section in the Obsidian check-in note that surfaces recent
[`serverless-memex`](https://github.com/mjacobs/serverless-memex) captures
for triage — chronological, with LLM-enriched tag chips.

**Status:** stable, in daily production since 2026-05.

Sibling of [`vault-review`](../vault-review/) and
[`agent-review`](../agent-review/). See [`DESIGN.md`](./DESIGN.md) for
the design rationale (in particular, why the section is a *triage
surface* and not an archive).

## What you get

Running `memex-review today` appends a section like this to
`journal/checkins/YYYY-MM-DD.md`:

```markdown
## memex-review — 2026-05-14 — inbox

_window: captures since 2026-05-13 EOD_

- **08:12** — the bug was in the retry loop, not the timeout `#debugging` `#agent-review`
- **10:47** — idea: weekly retro could pull from agent-review digests `#meta` `#agent-review`
- **14:03** — `pip install ruff` is much faster than installing it via Poetry `#tooling` `#python`
- **22:58** — voice memo: meeting takeaway re: Q2 priorities `#work` `#planning`

<!-- memex-review:daily=2026-05-14 generated_at=2026-05-15T04:00:00Z -->
```

The section is an **inbox for triage**, not a topical recap. Flat
chronological + inline tag chips. Each capture is one bullet; you either
copy it into a project note, jot a follow-up into a backlog note, or
decide it's noise. Then run `memex-review process` to advance the cursor.

## Install

```bash
uv tool install .
```

## Usage

```bash
memex-review run today
memex-review run yesterday
memex-review today           # alias
memex-review yesterday       # alias

memex-review run 2026-05-14
memex-review run 2026-05-10..2026-05-14

memex-review show 2026-05-14
memex-review reset 2026-05-14

memex-review run today --dry-run --print
```

## Triage workflow

The daily inbox section is a **triage surface**, not an archive. Captures
shown are everything created since the cursor — typically yesterday's
captures, surfaced overnight by the daily cron. The workflow:

1. Open today's check-in note in Obsidian.
2. Read the `## memex-review — … — inbox` section. For each capture,
   either copy/paste it into a project note, jot a follow-up into a
   backlog note, or just decide it's noise.
3. Run `memex-review process` to advance the cursor past yesterday.
   Tomorrow's section starts fresh.

```bash
memex-review process                     # advance cursor through yesterday EOD
memex-review process --through 2026-05-15

memex-review cursor                      # print current cursor
memex-review cursor --rewind 2026-05-10  # move cursor back to re-triage
memex-review cursor --init 2026-04-01    # first-time bootstrap override
```

`process` is idempotent (re-running advances no further) and refuses to
move past yesterday — for safety against fat-fingering a future date.
`cursor --rewind` refuses to move forward; that's what `process` is for.
`cursor --init` refuses if a cursor file already exists.

The cursor lives in the vault at `<vault>/state/memex-review.yaml` so it
syncs across machines alongside the check-in notes themselves.

If no cursor file exists yet, `run <date>` treats the start of the
requested date as the temporary cursor. That keeps a first manual
`memex-review run yesterday` useful while still letting `process` commit
the durable cursor once the inbox has been triaged.

## Configuration

Set via environment or `.env` in the working directory:

| Variable              | Default                | Description                                           |
| --------------------- | ---------------------- | ----------------------------------------------------- |
| `MEMEX_URL`           | _(required)_           | `serverless-memex` Worker base URL                    |
| `MEMEX_CLIENT_ID`     | _(required)_           | Cloudflare Access service-token client id             |
| `MEMEX_CLIENT_SECRET` | _(required)_           | Cloudflare Access service-token client secret         |
| `VAULT_PATH`          | `~/vault`              | Obsidian vault root                                   |
| `TZ`                  | `America/Los_Angeles`  | Timezone for day boundaries                           |

## Output

Daily sections land in `journal/checkins/YYYY-MM-DD.md` with marker:

```
<!-- memex-review:daily=2026-05-14 generated_at=2026-05-15T04:00:00Z -->
```

Sections are idempotent: re-running replaces the marked block in place;
human edits outside the block survive.

## Development

```bash
uv sync --group dev
uv run pytest
uv run memex-review --help
```

## See also

- [`DESIGN.md`](./DESIGN.md) — design rationale, why-not-tag-grouping.
- [`deploy/`](./deploy/) — cron wrapper for unattended daily runs.
- [`serverless-memex`](https://github.com/mjacobs/serverless-memex) — the
  backing capture store.
