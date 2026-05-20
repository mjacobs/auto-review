# agent-review

LLM-synthesized daily narrative report of activity across agent CLIs
(Claude Code, Codex, Gemini, OpenClaw, Hermes, …), built from the
unified `agentsview` Postgres schema and written idempotently into the
Obsidian check-in note.

**Status:** beta — `today` works end-to-end; cron-deployment parked
behind digest-cost tuning.

Sibling of [`vault-review`](../vault-review/) and
[`memex-review`](../memex-review/). The only sibling that does LLM
synthesis — extraction is deterministic SQL, but per-session digests
(Haiku) and the daily synthesis (Sonnet) are generative.
See [`DESIGN.md`](./DESIGN.md) for the full design.

## What you get

Running `agent-review today` appends a narrative section to
`journal/checkins/YYYY-MM-DD.md`:

```markdown
## agent-review — 2026-05-14

_window: 2026-05-14 · 6 sessions across 3 agents · ~2.4h interactive time_

**auto-review** — Two long Claude Code sessions focused on tightening
the `vault-review` deploy story. Morning: extracted `PLAN.md` to
`docs/history/` and added a context preamble so the original
implementation log is obviously historical, not current. Afternoon:
generalized openclaw references throughout deploy scripts to make the
repo readable as a recipe rather than a mirror of one home lab. 52 tests
still passing.

**serverless-memex** — One short Codex session adding the `before=`
cursor to `/thoughts`, with a follow-up Gemini session to verify the
backup-export walker matched the new pagination shape.

**incidental** — One Claude session abandoned mid-stream (vault git
push conflict, resolved by hand outside the agent).

<!-- agent-review:daily=2026-05-14 generated_at=2026-05-15T04:00:00Z -->
```

The shape is paragraphs grouped by inferred project, plus a header line
summarizing session count, agent breakdown, and rough interactive time.

## Install

```bash
uv sync
```

For production install:

```bash
uv tool install .
```

## Usage

```bash
uv run agent-review --help

# Phase-by-phase exercise:
uv run agent-review extract 2026-05-13 --print     # deterministic SQL extract only
uv run agent-review digest <session-id>             # per-session LLM digest
uv run agent-review today --dry-run --print         # full pipeline, no vault write
uv run agent-review yesterday                       # full pipeline, write to vault
```

## Architecture in one paragraph

`extract` pulls structured session data from `agentsview` Postgres with
no LLM. `digest` summarizes each session via Haiku in parallel (cached
in Postgres so re-runs are free). `synth` calls Sonnet once with all
digests + extracted scope to produce the day's narrative. `today`
chains all three and writes the result into the vault. The Postgres
cache is what makes mid-day re-runs cheap.

## Configuration

All via environment or `.env`:

| Variable             | Default                              | Description                                                          |
| -------------------- | ------------------------------------ | -------------------------------------------------------------------- |
| `PG_DSN`             | _(required)_                         | Postgres DSN for `agentsview`; omit password to use `PGPASSFILE` / `~/.pgpass` |
| `ANTHROPIC_API_KEY`  | _(required)_                         | Anthropic API key                                                    |
| `VAULT_PATH`         | `~/vault`                            | Obsidian vault root                                                  |
| `TZ`                 | `America/Los_Angeles`                | Timezone for day boundaries                                          |
| `MODEL_DIGEST`       | `claude-haiku-4-5-20251001`          | Model for per-session digests                                        |
| `MODEL_SYNTH`        | `claude-sonnet-4-6`                  | Model for daily narrative synthesis                                  |

## Output

Daily sections land in `journal/checkins/YYYY-MM-DD.md` with marker:

```
<!-- agent-review:daily=2026-05-14 generated_at=2026-05-15T04:00:00Z -->
```

Sections are idempotent: re-running replaces the marked block in place;
human edits outside the block survive.

## Development

```bash
uv sync --group dev
uv run pytest
```

## See also

- [`DESIGN.md`](./DESIGN.md) — schema, prompts, redaction pass, open questions.
- [`migrations/`](./migrations/) — SQL for the `agent_review` Postgres schema.
- [`deploy/`](./deploy/) — cron wrapper for unattended daily runs.
