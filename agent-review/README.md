# agent-review

Daily narrative reports of activity across agent CLIs (Claude, Codex, Gemini,
OpenClaw, Hermes, Forge, …), built from the unified `agentsview` Postgres
schema and written into the Obsidian vault.

See [DESIGN.md](./DESIGN.md) for the full design.

## Quick start

```bash
uv sync
cp .env.example .env   # edit values
uv run agent-review --help

# Phase-by-phase exercise:
uv run agent-review extract 2026-05-13 --print
uv run agent-review digest <session-id>
uv run agent-review today --dry-run --print
uv run agent-review yesterday
```

## Layout

- `src/agent_review/` — package
- `migrations/` — SQL for the `agent_review` schema
- `deploy/` — cron wrapper and install notes
- `tests/` — pytest
- `DESIGN.md` — design doc

## Configuration

All via environment / `.env`:

- `PG_DSN` — Postgres DSN for `agentsview`; omit the password to use `PGPASSFILE`, `./.pgpass`, or `~/.pgpass`
- `ANTHROPIC_API_KEY` — Anthropic API key
- `VAULT_PATH` — Obsidian vault root (default `~/vault`)
- `TZ` — timezone for day boundaries (default `America/Los_Angeles`)
- `MODEL_DIGEST` — model for per-session digests (default Haiku 4.5)
- `MODEL_SYNTH` — model for daily synthesis (default Sonnet 4.6)
