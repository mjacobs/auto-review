# memex-review

Daily narrative recap of [cf-memex](https://github.com/mjacobs/serverless-memex)
captures, written idempotently into the Obsidian vault check-in note.

Sibling of [vault-review](../vault-review/) and [agent-review](../agent-review/).
See [DESIGN.md](./DESIGN.md) for design rationale.

## Install

```bash
uv sync
uv tool install .   # once stable
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

## Processing

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
memex-review process                   # advance cursor through yesterday EOD
memex-review process --through 2026-05-15

memex-review cursor                    # print current cursor
memex-review cursor --rewind 2026-05-10  # move cursor back to re-triage
memex-review cursor --init 2026-04-01    # first-time bootstrap override
```

`process` is idempotent (re-running advances no further) and refuses to
move past yesterday — for safety against fat-fingering a future date.
`cursor --rewind` refuses to move forward; that's what `process` is for.
`cursor --init` refuses if a cursor file already exists.

The cursor lives in the vault at `~/vault/state/memex-review.yaml` so it
syncs across machines alongside the check-in notes themselves.

## Configuration

Set via environment or `.env` in the working directory:

| Variable | Default | Description |
|---|---|---|
| `MEMEX_URL` | _(required)_ | cf-memex Worker base URL |
| `MEMEX_CLIENT_ID` | _(required)_ | Cloudflare Access service-token client id |
| `MEMEX_CLIENT_SECRET` | _(required)_ | Cloudflare Access service-token client secret |
| `VAULT_PATH` | `~/vault` | Obsidian vault root |
| `TZ` | `America/Los_Angeles` | Timezone for day boundaries |

On the dev box, `MEMEX_*` already live in `~/.secrets`.
