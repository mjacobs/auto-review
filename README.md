# auto-review

Three sibling Python tools that synthesize raw daily activity — git
diffs over an Obsidian vault, agent CLI session traces, and ambient
notes captures — into narrative recap sections written idempotently
into the vault's daily check-in note.

Each tool reads one source, renders one section, and writes it into
the same check-in file. Re-runs replace the section in place; hand-edits
outside the marker survive.

## The three siblings

| Tool                                    | Source                                                            | Output                                            |
| :-------------------------------------- | :---------------------------------------------------------------- | :------------------------------------------------ |
| [`vault-review`](./vault-review/)       | `git log` over the vault                                          | Deterministic delta recap (what notes changed)    |
| [`agent-review`](./agent-review/)       | `agentsview` Postgres (Claude / Codex / Gemini CLI session logs)  | LLM-synthesized daily narrative report            |
| [`memex-review`](./memex-review/)       | [`serverless-memex`](https://github.com/mjacobs/serverless-memex) `/thoughts` API | Deterministic capture-inbox section (triage surface) |

The result, in a single day's check-in note:

```
journal/checkins/2026-05-19.md
├── ## vault-review — 2026-05-19      ← what you wrote/edited in the vault
├── ## agent-review — 2026-05-19      ← what you did across Claude/Codex/etc.
└── ## memex-review — 2026-05-19      ← what you captured (inbox for triage)
```

## Why a monorepo

The three tools are independently installable and independently deployed.
They live together because they share — by deliberate convention — the
same shape:

- **Same CLI verbs.** `run today`, `run yesterday`, `run YYYY-MM-DD`,
  `run YYYY-MM-DD..YYYY-MM-DD`, `show`, `reset`, with global `--dry-run`
  and `--print` flags.
- **Same project layout** (`config.py`, `<source>.py`, `dossier.py`,
  `vault.py`, `cli.py` — see [`AGENTS.md`](./AGENTS.md) for the mirror
  spec).
- **Same marker-bracketed idempotency.** Every section is wrapped in a
  predictable HTML comment marker; the writer strips and replaces by
  regex. Human edits outside the marker are preserved.
- **Same `pydantic-settings` config shape.** All config via env or
  `.env`; `VAULT_PATH` and `TZ` are common across all three, plus
  per-source credentials.

The monorepo is what makes the shape enforceable. Drifting one tool away
from the family pattern is visible in a diff; without colocation, the
three would slowly stop behaving like peers.

## Design principles

**Deterministic where possible; LLM only where it adds clear value.**
Two of the three tools have no LLM at all — `vault-review` is pure
`git log` → markdown, `memex-review` is pure REST hydration → markdown.
Only `agent-review` calls an LLM (Claude), and even there the extraction
phase is deterministic SQL and only the digest+synthesis stages are
generative. This keeps cost, latency, and reproducibility predictable.

**Capture-side vs synthesis-side.** The system separates raw capture
(`serverless-memex`, agent CLI logs, raw git diffs) from synthesis (the
recap sections in the check-in note). The check-in note is the synthesis
surface a human reads; the capture surfaces are the firehose the tools
read.

**The vault is the durable store.** Each tool writes back into the vault
git repo, which auto-syncs across machines. There is no separate
database of "recap state" — if you can reach your vault, you have the
full history.

**Hosting is decoupled from the workloads.** Deterministic periodic
jobs (these three tools) have a different security/scrutiny profile
from agent runtimes, even when they share a box. See
[`decisions/001-periodic-jobs-vs-agent-runtime.md`](./decisions/001-periodic-jobs-vs-agent-runtime.md)
for the ADR.

## Quickstart

Each tool stands alone — pick whichever source you care about first.

```bash
# vault-review — the simplest entry point (no LLM, no Postgres, no
# external service; just a git-tracked vault).
cd vault-review/
uv tool install .
vault-review run today --dry-run --print

# memex-review — requires a deployed serverless-memex instance.
cd memex-review/
uv tool install .
memex-review run today --dry-run --print

# agent-review — requires an agentsview Postgres + Anthropic API key.
cd agent-review/
uv sync
uv run agent-review today --dry-run --print
```

All three default to `VAULT_PATH=~/vault` and `TZ=America/Los_Angeles`.
Override via `.env` or environment variables — see each tool's README
for the full config surface.

## Deployment

All three are designed to run as overnight cron jobs on a Linux host
with the vault checked out locally. Each tool ships a
`deploy/run-<tool>-daily.sh` wrapper that:

1. Sources credentials from `~/.secrets`.
2. Runs the tool for "yesterday".
3. Commits and pushes the resulting check-in note change.

Stagger the cron lines by at least 30 minutes per tool so they don't
race on the vault git lock. See [`AGENTS.md`](./AGENTS.md) for the
deployment recipe.

## Status

| Tool          | Status                | Running daily since |
| :------------ | :-------------------- | :------------------ |
| `vault-review` | Stable, in production | 2026-04             |
| `memex-review` | Stable, in production | 2026-05             |
| `agent-review` | Beta — `today` works end-to-end; cron deploy gated on credential-hygiene (dedicated PG user + Anthropic key) | not yet daily       |

## Related projects

- [`serverless-memex`](https://github.com/mjacobs/serverless-memex) — the
  Cloudflare Worker that backs `memex-review`. MCP server for capture-side
  knowledge storage.

## Repo layout

```
auto-review/
├── README.md                 # this file
├── AGENTS.md                 # contributor guide (mirror layout, deploy recipe)
├── decisions/                # ADRs
├── doctor/                   # cron health-check wrapper across all three siblings
├── vault-review/             # tool 1
├── agent-review/             # tool 2
└── memex-review/             # tool 3
```

## License

MIT — see [`LICENSE`](./LICENSE).
