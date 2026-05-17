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
