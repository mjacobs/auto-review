# agent-review — design

A CLI that reads aggregated agent-session data from Postgres (`agentsview` schema)
and produces a daily narrative report, appended to the relevant Obsidian
check-in note.

## Goals

- One **daily narrative** per day, written by Claude, that reads like a
  status update — what was worked on, what shipped, what got stuck.
- **Per-project bullet roll-up**, **stats block**, and **notable artifacts**
  (commits/PRs/files) below the narrative.
- **Links back to source sessions** so any item can be drilled in via psql or a
  future viewer.
- **Idempotent**: re-running a day is cheap — per-session digests are cached.
- Manual CLI now (`agent-review today`, `agent-review 2026-05-14`, `agent-review --range A..B`); easy to wire to a timer later.

## Non-goals (v1)

- No web UI — design leaves room for one (digests live in the DB) but ships CLI-only.
- No automatic scheduling / no hermes-cron registration.
- No cross-day synthesis (weekly/monthly roll-ups are a phase 2 lever).
- No dashboard for the data already in `agentsview` — that exists separately.

## Source data

Live database: a Postgres instance (typically `<pg-host>:5432/agentsview`) · schema `agentsview`.

| Table                | Role                                                        |
|----------------------|-------------------------------------------------------------|
| `sessions`           | one row per agent run + rich rollups (outcome, health, tokens, automated flag, parent/subagent, cwd, git_branch) |
| `messages`           | `(session_id, ordinal)`; `role`, `content`, `thinking_text`, `is_sidechain`, `is_compact_boundary`, per-msg tokens |
| `tool_calls`         | `tool_name`, `category`, `input_json`, `result_content`, `subagent_session_id`  |
| `tool_result_events` | currently empty — derive results from `tool_calls.result_content` instead |
| `model_pricing`      | `$ / Mtok` per model pattern → cost math                    |

### Scope filter (applied at extract)

A session is **in-scope** for a day if all hold:

1. `started_at::date = <report_date>` (in user's local TZ).
2. `is_automated = false`.
3. `message_count >= 3` **OR** `has_tool_calls = true`.
4. `first_message` is not a pure slash-command (`/exit`, `/model`, `/help`, `/clear`, etc.).
5. `outcome != 'unknown'` **OR** the session edited/wrote files (signal of real work).

These thresholds are configurable; defaults chosen from observed noise patterns
(many `/exit`/`/model` and connectivity-test sessions in the data).

Subagent sessions (`parent_session_id IS NOT NULL`) are folded into the parent's
digest, not summarized independently.

## Architecture

```
┌──────────────────────────┐
│ Postgres (agentsview)    │
└────────────┬─────────────┘
             │ SQL extract (per day, scope filter)
             ▼
┌──────────────────────────┐
│ Stage 1: Extract         │  raw session bundles + deterministic
│  - session metadata      │  artifact extraction (commits, files)
│  - compressed transcript │
│  - tool-call summary     │
└────────────┬─────────────┘
             │
             ▼
┌──────────────────────────┐    cache lookup by (session_id, data_version)
│ Stage 2: Per-session     │ ◄──────────────────────────────────────────┐
│  digest (Claude)         │                                            │
│  → structured JSON       │ ─► UPSERT agent_review.session_digests ────┘
└────────────┬─────────────┘
             │
             ▼
┌──────────────────────────┐
│ Stage 3: Daily synthesis │ ─► UPSERT agent_review.daily_reports
│  (Claude → markdown)     │
└────────────┬─────────────┘
             │
             ▼
┌──────────────────────────┐
│ Stage 4: Vault writer    │ ─► append/replace section in
│                          │     ~/vault/journal/checkins/YYYY-MM-DD.md
└──────────────────────────┘
```

Two stages because heavy days don't fit in one call: 2026-05-04 was 77
sessions / 4383 messages / ~750k tokens of raw text. Per-session digests
collapse that to a few KB of structured JSON the synthesis stage can read in
one shot.

### Stage 1 — extract

Pure SQL + Python. Per session, build:

- **Header** — id, agent, project (prefer `cwd`/`git_branch` over noisy `project`), started/ended, outcome, health, message_count, peak_context_tokens, total_output_tokens.
- **Compressed transcript** — drop `thinking_text`, drop sidechain noise, dedupe identical tool outputs, truncate any single message >8KB to head+tail with `…[N bytes elided]…`. Keep first user message verbatim (it's usually the prompt that defines the session).
- **Tool-call summary** — counts by `category`, top 10 distinct `Bash` commands, file paths touched (Read/Edit/Write/Glob).
- **Artifact extraction** (deterministic, no LLM):
  - `git commit` / `git push` / `gh pr create` invocations from `Bash` calls → commit messages, PR URLs.
  - Files written/edited (from `Edit`/`Write` `input_json`).
  - Files created (Write where path didn't previously exist in same session).
  - Outbound tool calls (Linear, Vercel, gh) when present.

Subagents: a session with `parent_session_id` set has its compressed transcript
appended to the parent's bundle under a `### subagent: <agent>` heading.

### Stage 2 — per-session digest

Cache key: `(session_id, sessions.data_version)`. If a row exists in
`agent_review.session_digests` with matching `data_version`, skip the LLM call.

Prompt structure (uses **prompt caching** — system prompt + schema cached
across all sessions in a run):

```
SYSTEM (cached):
  You summarize a single agent coding session into structured JSON.
  Schema: { summary: str (≤3 sentences),
            project: str,
            tags: [str],
            key_changes: [str],
            artifacts: [{kind, ref, note}],
            blockers: [str],
            outcome: "shipped" | "progressed" | "stuck" | "abandoned" | "exploration",
            confidence: "high" | "medium" | "low" }
  Rules: ...

USER:
  <session header + compressed transcript + tool-call summary + extracted artifacts>
```

Model: **Claude Haiku 4.5** for digests (cheap, fast, plenty for
single-session summarization). Configurable per-stage.

### Stage 3 — daily synthesis

Inputs: all in-scope session digests for the date + the day's aggregated
artifacts + day-level stats.

```
SYSTEM (cached):
  You write a daily engineering report for one developer (mj). Voice: terse,
  factual, first-person-singular ("I"). Lead with what shipped, follow with
  what progressed, note what's stuck. Group by project. No marketing language.
  Output Markdown matching this template: ...

USER:
  date: 2026-05-14
  digests: [ ... ]   ← the JSON rows from stage 2
  artifacts: { commits: [...], prs: [...], files_touched: [...] }
  stats: { sessions: N, agents: {...}, tokens: {...}, est_cost_usd: $X.XX }
```

Model: **Claude Sonnet 4.6** for synthesis (better narrative judgment).

### Stage 4 — vault writer

Target: `~/vault/journal/checkins/YYYY-MM-DD.md`. If the file doesn't exist,
create it from `~/vault/templates/daily.md` (with frontmatter
`tags: [journal/checkin]`, `date:` filled in).

Append (or **replace**, on re-run) a single section, mirroring the existing
vault-agent `## delta — …` convention:

```markdown
## agent-review — 2026-05-14 06:00

_window: 2026-05-14 00:00 → 23:59 local · 24 sessions · 4 projects · ~$0.08_

<narrative paragraph(s) from Stage 3>

### by project

- **agent-review** — <bullet> ([sess](agentsview://session/abc), [sess](…))
- **vault** — <bullet>
- ...

### artifacts

- commit `a1b2c3d` — "fix: handle empty sync metadata" (`agent-review`)
- PR #42 — "Add daily digest cache" (`agent-review`)
- new file `DESIGN.md` (`agent-review`)

### stats

| sessions | agents | msgs | input tok | output tok | est. cost |
|---------:|:-------|-----:|----------:|-----------:|----------:|
| 24       | claude×18, codex×4, gemini×2 | 386 | 2.1M | 18k | $0.082 |

<!-- agent-review:report_date=2026-05-14 generated_at=2026-05-14T06:00:12-07:00 -->
```

Re-runs detect the trailing HTML comment marker and replace the section
in-place — no duplicate sections, no diff churn in the vault git repo.

Session links use the `agentsview://session/<id>` URI scheme (not yet
resolvable; reserved for the future viewer). Until then they render as inert
links — fine for grep + paste-into-psql.

## Storage

New schema **`agent_review`** in the same database (separate from `agentsview`,
which is owned by the upstream sync pipeline and should stay read-only to us).

```sql
CREATE SCHEMA agent_review;

CREATE TABLE agent_review.session_digests (
  session_id    text PRIMARY KEY REFERENCES agentsview.sessions(id) ON DELETE CASCADE,
  data_version  integer NOT NULL,           -- copied from sessions.data_version at digest time
  model         text NOT NULL,
  prompt_tokens integer NOT NULL,
  output_tokens integer NOT NULL,
  cached_tokens integer NOT NULL DEFAULT 0,
  digest        jsonb NOT NULL,             -- the structured summary
  generated_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE agent_review.daily_reports (
  report_date        date PRIMARY KEY,
  generated_at       timestamptz NOT NULL DEFAULT now(),
  model              text NOT NULL,
  sessions_included  text[] NOT NULL,        -- session ids
  narrative_md       text NOT NULL,          -- the rendered section body
  stats              jsonb NOT NULL,
  prompt_tokens      integer NOT NULL,
  output_tokens      integer NOT NULL,
  cached_tokens      integer NOT NULL DEFAULT 0,
  est_cost_usd       numeric(10, 4) NOT NULL
);

CREATE INDEX idx_session_digests_generated_at ON agent_review.session_digests(generated_at);
```

`data_version` on `agentsview.sessions` increments when the upstream pipeline
re-syncs a session, so it's a clean cache-invalidation key.

## CLI surface

Implemented with `click`. Single binary `agent-review`.

```
agent-review today                    # synthesize today (so far)
agent-review yesterday                # convenience
agent-review 2026-05-14               # one date
agent-review 2026-05-10..2026-05-14   # range, one report per day
agent-review --range last-week        # convenience

agent-review digest <session-id>      # run only stage 1+2 for one session
agent-review show 2026-05-14          # print latest stored report to stdout
agent-review reset 2026-05-14         # delete cached digests + report for re-run

# global flags
  --dry-run            # don't write to vault, don't write to DB
  --no-vault           # write to DB only
  --print              # also print result to stdout
  --model-digest haiku-4.5
  --model-synth sonnet-4.6
  --tz America/Los_Angeles  # default from $TZ
  --vault ~/vault           # default
  --since-version N    # force re-digest of sessions whose data_version > N
```

Exit codes: `0` success, `2` no in-scope sessions for date, `3` upstream DB
unavailable, `4` Anthropic API failure, `5` vault write failure.

## Tech stack

- **Python 3.12**, managed with **uv** (`uv venv`, `uv pip`, `pyproject.toml`).
- `anthropic` (official SDK) — prompt caching enabled.
- `psycopg[binary]` v3 — connection pooled at the process level.
- `click` — CLI.
- `jinja2` — section template.
- `python-frontmatter` — round-trip vault note frontmatter cleanly.
- `pydantic` — typed config + digest schema validation.
- `tenacity` — retry on Anthropic 429/5xx.
- `pytest` + `pytest-recording` (VCR-style) for stable LLM-call tests.

Project layout:

```
agent-review/
├── pyproject.toml
├── DESIGN.md
├── README.md
├── .env.example                  # PG_DSN, ANTHROPIC_API_KEY, VAULT_PATH, TZ
├── migrations/
│   └── 001_init.sql              # creates agent_review.* tables
├── src/agent_review/
│   ├── __init__.py
│   ├── cli.py                    # click entrypoint
│   ├── config.py                 # pydantic settings
│   ├── db.py                     # psycopg + queries
│   ├── extract.py                # stage 1
│   ├── digest.py                 # stage 2 (per-session, cached)
│   ├── synth.py                  # stage 3 (daily narrative)
│   ├── vault.py                  # stage 4 (note read/write/replace)
│   ├── artifacts.py              # deterministic commit/file/PR extraction
│   ├── pricing.py                # cost math from agentsview.model_pricing
│   ├── prompts/
│   │   ├── digest_system.md
│   │   └── synth_system.md
│   └── templates/
│       └── daily_section.md.j2
└── tests/
    ├── fixtures/                  # captured session bundles
    ├── test_extract.py
    ├── test_artifacts.py
    ├── test_vault.py
    └── test_digest_smoke.py       # @pytest.mark.live, opt-in
```

## Cost & token budget

Rough sizing from observed data (5 months, 567 sessions, 14k messages):

- **Per-session digest** (Haiku 4.5): mean ~6KB compressed transcript →
  ~1.5k input tok / ~250 output tok ≈ **$0.0011 / session** (cached system
  prompt amortizes to ~free across the run).
- **Daily synthesis** (Sonnet 4.6): ~24 digests × 400 tok ≈ ~10k input tok
  / ~1.5k output tok ≈ **$0.052 / day**.
- **Backfill all 567 sessions once**: ~$0.65 of digest spend.
- **Steady-state**: ~10 in-scope sessions/day × $0.0011 + $0.05 ≈ **$0.06/day**
  (~$22/year).

The cache is the key lever — re-running today (e.g. mid-day refresh, or after
upstream re-sync of one session) only re-digests dirty sessions and re-runs
synthesis.

## Idempotency & re-runs

- **Stage 2** is keyed on `(session_id, data_version)`; safe to re-run cheaply.
- **Stage 3** is keyed on `report_date`; UPSERT replaces.
- **Stage 4** finds the section by HTML-comment marker and replaces in place;
  preserves any human edits to the rest of the file.
- `agent-review reset DATE` is the explicit "blow away cache and re-run".

## Phased rollout

| Phase | Scope                                                                        |
|-------|------------------------------------------------------------------------------|
| 0     | Scaffold + migrations + config + DB connection                                |
| 1     | Stage 1 extract + artifact extraction (no LLM yet); `agent-review extract DATE --print` |
| 2     | Stage 2 digest with cache; `agent-review digest <session-id>`                 |
| 3     | Stage 3 synthesis; `agent-review today --no-vault --print`                    |
| 4     | Stage 4 vault writer + `today`/`yesterday`/range CLI                          |
| 5     | Backfill last 30 days; tune prompts against real output                       |
| 6     | (later) Weekly synthesis from daily digests; systemd timer; viewer            |

## Open questions

1. **Timezone** for the day boundary — sessions may span several machines
   but a single human operator is typically in one TZ. Default to `$TZ` /
   `America/Los_Angeles`?
2. **`project` field** is noisy (`workspace`/`mj` catch-alls). Should the
   digest infer project from `cwd` + `git_branch` when those are present?
   Recommend: **yes**, and surface the inferred project in the digest output.
3. **Mid-day re-runs**: do you want `agent-review today` to be safe to run
   any time (replacing the section), or should it refuse if "today" isn't
   over yet? Recommend: **safe to run any time**, with `_window:` in the
   header reflecting the actual cut-off.
4. **Subagents in `claude` (Opus 4.7)** show up as `parent_session_id`-linked
   rows; some agents (codex, gemini) may not. Confirm fold-into-parent is
   correct for all agents, or keep some agent-specific behavior.
5. **Secrets handling** — first-user-message can include pasted file content
   (agent CLI config files routinely carry credentials). Want a redaction pass
   before sending to Anthropic? Recommend: **yes, basic regex redactor**
   (`AKIA…`, `gh[ps]_…`, `sk-…`, `ANTHROPIC_API_KEY=…`, `password=…`,
   `.pgpass`-style lines).
