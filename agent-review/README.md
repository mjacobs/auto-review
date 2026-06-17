# agent-review

LLM-synthesized daily narrative report of activity across agent CLIs
(Claude Code, Codex, Gemini, OpenClaw, Hermes, …), built from the
unified `agentsview` Postgres schema and written idempotently into the
Obsidian check-in note.

**Status:** beta — `today` works end-to-end. By default the LLM calls run via
`claude -p` against the **Claude Max subscription** (see
[LLM backends](#llm-backends) below), so the marginal API cost is $0 — it draws
on the subscription's ~$200/mo programmatic quota instead of a Console key. The
legacy direct-API path is still available behind `LLM_BACKEND=api`.

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
generalized deploy scripts to make the repo readable as a recipe rather
than a mirror of one home lab. 52 tests still passing.

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

| Variable                              | Default                              | Description                                                          |
| ------------------------------------- | ------------------------------------ | -------------------------------------------------------------------- |
| `PG_DSN`                              | _(required)_                         | Postgres DSN; omit password to use `PGPASSFILE` / `~/.pgpass`       |
| `LLM_BACKEND`                         | `claude_cli`                         | `claude_cli` → run digest/synth via `claude -p` (Claude Max subscription); `api` → the anthropic SDK. See [LLM backends](#llm-backends) |
| `LLM_API_KEY`                         | _(required iff `LLM_BACKEND=api`)_   | API key sent to the LLM endpoint. When `LLM_BASE_URL` is set this is typically a LiteLLM virtual key; otherwise a direct provider key. Ignored under `claude_cli` |
| `LLM_BASE_URL`                        | _(unset → api.anthropic.com)_        | `api` backend only. Override the LLM SDK base URL — e.g. a LiteLLM gateway (`https://llm.example.internal`) for a per-client virtual key |
| `CLAUDE_CLI_BIN`                      | `claude`                             | `claude_cli` backend: path to the Claude Code binary                 |
| `CLAUDE_CLI_TIMEOUT`                  | `300`                                | `claude_cli` backend: per-call timeout, seconds                      |
| `CLAUDE_CLI_EXTRA_ARGS`              | _(empty)_                            | `claude_cli` backend: extra flags appended to every `claude -p` (shlex-split), e.g. `--max-budget-usd 0.50` |
| `VAULT_PATH`                          | `~/vault`                            | Obsidian vault root                                                  |
| `TZ`                                  | `America/Los_Angeles`                | Timezone for day boundaries                                          |
| `MODEL_DIGEST`                        | `claude-haiku-4-5-20251001`          | Model for per-session digests. Passed to `claude --model` (`claude_cli`) or used as the SDK/gateway model id (`api`) |
| `MODEL_SYNTH`                         | `claude-sonnet-4-6`                  | Model for daily narrative synthesis. Same as `MODEL_DIGEST`          |
| `AGENT_REVIEW_PG_SCHEMA`              | `agentsview`                         | Schema name for the upstream read-only database                      |
| `AGENT_REVIEW_AUTOMATED_ID_PREFIXES`  | `hermes:cron_`                       | Comma-separated session-id prefixes treated as automated (non-human) when the upstream `is_automated` flag is unreliable |

### LLM backends

agent-review is the only sibling that calls an LLM (Haiku for per-session
digests, Sonnet for the daily narrative). Two backends, picked by `LLM_BACKEND`:

**`claude_cli` (default).** Each call shells out to `claude -p` (payload on
stdin), so usage is billed against the **Claude Max subscription's programmatic
quota** rather than a Console API key. The invocation is locked down to a pure
completion — the flags it always passes:

- `--model <id>` / `--system-prompt <prompt>` — our model + prompt
- `--output-format json` — parse the result event's `structured_output` / `result` + `usage`
- `--json-schema <schema>` — **digest only**; forces schema-valid structured output
- `--safe-mode` + `--strict-mcp-config` — strip CLAUDE.md / hooks / MCP / plugins (cheaper, deterministic)
- `--setting-sources ""` — load no `settings.json` (so a host `apiKeyHelper` can't divert billing)
- `--tools ""` — disable every tool, so the call can never run anything on the host

Auth: the host's `claude` must be logged in to the subscription. For unattended
cron, mint a long-lived token once and store it in `~/.secrets`:

```bash
claude setup-token            # interactive, one-time; prints a token
# add to ~/.secrets:  export CLAUDE_CODE_OAUTH_TOKEN=...
```

To keep billing pinned to the subscription on a shared host, agent-review (a)
scrubs every off-subscription auth/routing var from the `claude` subprocess env
— direct API keys, `apiKeyHelper`'s env form (`CLAUDE_CODE_API_KEY_HELPER`), and
the Bedrock/Vertex switches (`CLAUDE_CODE_USE_BEDROCK` / `…_USE_VERTEX` / …) —
and (b) passes `--setting-sources ""` so a `settings.json` `apiKeyHelper` (which
`--safe-mode` would otherwise leave active and which *outranks* OAuth) is never
loaded. Recorded `est_cost_usd` is the *equivalent* API cost (a proxy for quota
burn), computed from token usage exactly as the `api` backend is.

**`api` (legacy).** The `anthropic` SDK against `LLM_API_KEY` / `LLM_BASE_URL`
(direct or via a LiteLLM gateway). Requires `LLM_API_KEY`.

### Routing via LiteLLM (`api` backend only)

> Applies only when `LLM_BACKEND=api`. The default `claude_cli` backend talks to
> the subscription directly and ignores `LLM_BASE_URL`.

Setting `LLM_BASE_URL` points the underlying LLM SDK at a LiteLLM gateway,
which translates `/v1/messages` to whatever backend the model alias maps
to (Anthropic, OpenAI, Gemini, or a local llama.cpp/vLLM host). Benefits:

- **Credential isolation.** Cron host holds a LiteLLM virtual key scoped
  to agent-review, not a shared provider key. Revoking the cron's access
  is one gateway call.
- **Per-client logging and rate limits** via the gateway.
- **Backend flexibility.** Swap `MODEL_DIGEST` / `MODEL_SYNTH` to a local
  alias (e.g. `local-fast`, `local-long`) without touching agent-review.

Example cron-host `.env` fragment:

```env
LLM_BASE_URL=https://llm.example.internal
LLM_API_KEY=sk-<litellm-virtual-key-for-agent-review>
MODEL_DIGEST=claude-haiku-4-5-20251001    # or e.g. local-fast
MODEL_SYNTH=claude-sonnet-4-6             # or e.g. local-long
```

The model names must be registered on the gateway. The default
`claude-*` IDs assume the gateway has Anthropic models added to its
model list; if not, use one of the gateway's existing aliases.

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
