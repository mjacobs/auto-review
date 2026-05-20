# vault-review — implementation plan (historical)

> **Note (preserved for context, not a current spec).**
> This is the original implementation plan that guided the v1 build-out
> of vault-review. It's kept here as historical context — useful for
> understanding *why* the codebase looks the way it does, but **not** an
> accurate description of the tool today. For current usage and design
> see [`../../README.md`](../../README.md) and
> [`../../DESIGN.md`](../../DESIGN.md).

Port the `recap` path of an earlier in-vault prototype (`vault-agent`)
into a standalone Python package at `vault-review/`, modeled directly on
`../agent-review/`.

## Goal

Daily and weekly narrative recaps of vault activity, derived deterministically
from `git diff` over the vault repo, written idempotently into the Obsidian
vault. Same shape, knobs, and idempotency story as `agent-review` so the two
tools behave like siblings.

## Non-goals (v1)

- No Telegram delivery, no `git commit/push` — pure markdown writer. The
  openclaw cron wrapper keeps owning side effects until the future
  "streamline agent harness" project moves them.
- No Postgres. File-backed via section markers in vault notes. Note in
  DESIGN.md that a `vault_review` schema is a viable later extension.
- No LLM call. Recap is deterministic post-ADR-006; no `anthropic` dep,
  no API key.
- No port of `checkin` / `capture` / `signal` / `snapshot` / `render` /
  `doctor`. Those stay in the vault-agent script (or get deleted there;
  see "Out of scope cleanups").

## Package layout

Mirror `agent-review/` exactly so the two are interchangeable to read:

```
vault-review/
├── pyproject.toml              # name=vault-review, script=vault-review
├── README.md
├── DESIGN.md
├── .env.example                # VAULT_PATH, TZ
├── .gitignore
├── src/vault_review/
│   ├── __init__.py
│   ├── cli.py                  # click; verbs match agent-review
│   ├── config.py               # pydantic-settings
│   ├── gitdelta.py             # git-log → events  (was _git_delta_events)
│   ├── dossier.py              # events → markdown (was _render_dossier, _summarize_file, _group_of)
│   ├── weekly.py               # ISO-week math + weekly synthesis rendering
│   └── vault.py                # marker-aware section writer (daily + weekly)
└── tests/
    ├── __init__.py
    ├── test_gitdelta.py
    ├── test_dossier.py
    ├── test_vault.py           # marker replace-in-place, frontmatter preserve
    └── fixtures/
```

Dependencies (minimal — no anthropic, no psycopg):

```
click, pydantic, pydantic-settings, python-frontmatter, python-dateutil
```

## CLI surface

Aligned with agent-review:

| Command | Behavior |
|---|---|
| `vault-review run [DATE\|today\|yesterday\|A..B\|last-week]` | Daily dossier. Default `today`. Writes to `journal/checkins/YYYY-MM-DD.md`. |
| `vault-review today` / `yesterday` | Aliases for `run today` / `run yesterday`. |
| `vault-review run-weekly [WEEK\|this-week\|last-week\|YYYY-W##]` | Weekly synthesis. Writes to `journal/weekly/YYYY-W##.md`. |
| `vault-review show DATE` | Print the current vault section for that date. |
| `vault-review show-weekly WEEK` | Same, for the weekly note. |
| `vault-review reset DATE` / `reset-weekly WEEK` | Remove the marked section. |
| Global flags | `--dry-run` (don't write), `--print` (also echo section to stdout). |

No `--force` — there's no cache to invalidate. Rerunning re-renders from
`git diff` and replaces the marked section.

## Idempotency

Same pattern as `agent-review/src/agent_review/vault.py:21`:

- Daily marker: `<!-- vault-review:daily=YYYY-MM-DD generated_at=… -->`
- Weekly marker: `<!-- vault-review:weekly=YYYY-W## generated_at=… -->`
- Section regex spans from `## vault-review …` heading through the marker.
- `write_section` loads frontmatter, strips the existing marked section,
  appends the new one, writes back. Creates the file with default
  frontmatter if absent. Human edits outside the marked section survive.

## Implementation phases

Each phase is a self-contained commit. Order matters; phases 1–4 are
sequential, phase 5 can run in parallel with phase 4.

### Phase 1 — scaffold

- `pyproject.toml`, `.env.example`, `.gitignore`, empty `src/vault_review/`
  package with `__init__.py` and `config.py` (pydantic-settings:
  `vault_path: Path = ~/vault`, `tz_name: str = "America/Los_Angeles"`).
- `uv sync` clean, `uv run vault-review --help` returns a stub.

### Phase 2 — port the deterministic core

Translate from `vault-agent` lines 738–860:

- `gitdelta.py` ← `_git_delta_events` (lines 751–783). Parameterize the
  `since` arg so it takes either a date or an ISO-week range, not just a
  relative spec. Strip the openclaw-specific filtering hooks that aren't
  needed.
- `dossier.py` ← `_summarize_file` (784–817), `_group_of` (818–824),
  `_render_dossier` (825–860). No structural change.
- Drop `_compose_telegram` entirely. Drop the "narrative deltas only;
  scripts/configs are not signal" comment about signal — dead context.

### Phase 3 — vault writer with markers

- `vault.py` modeled on `agent-review/src/agent_review/vault.py`. Two
  marker variants (daily / weekly), two pairs of `write_/read_/remove_`
  helpers, or one parameterized pair. Lean toward parameterized — the
  regex template is the only thing that varies.
- File targets: `journal/checkins/YYYY-MM-DD.md` for daily,
  `journal/weekly/YYYY-W##.md` for weekly. Default frontmatter for both.

### Phase 4 — CLI

- `cli.py` modeled on `agent-review/src/agent_review/cli.py`. Reuse the
  `_parse_date` / `_parse_range` shape; add `_parse_week` for ISO-week
  parsing (`this-week`, `last-week`, `YYYY-W##`).
- `_run_one(date)` → extract events for that day → render dossier →
  write section (unless `--dry-run`) → optionally `--print`.
- `_run_weekly_one(week)` symmetric.
- `show` / `reset` thin wrappers around `vault.read_section` /
  `vault.remove_section`.

### Phase 5 — tests (Sonnet subagent OK)

Self-contained, mechanical translation of `agent-review/tests/` patterns:

- `test_vault.py` — fixtures: temp dir with a fake `journal/checkins/`,
  assert marker replace is in-place, frontmatter survives, repeated runs
  produce identical files.
- `test_gitdelta.py` — fixture: a tiny git repo with a few commits across
  two days. Assert event grouping by date and by path.
- `test_dossier.py` — feed canned events, snapshot the markdown output.

**Subagent brief**: "Port the test patterns from
`auto-review/agent-review/tests/test_artifacts.py` and `test_redaction.py`
to cover `vault_review/vault.py`, `gitdelta.py`, `dossier.py`. Use the
same pytest style, fixture layout, and snapshot approach. Don't invent
new behavior — only test what's already implemented in phases 2–3."
Verify the diff myself before commit.

### Phase 6 — DESIGN.md + README.md

Short docs. DESIGN.md covers: goals, the marker idempotency story, the
deferred-PG-schema note, and a one-paragraph "future: serverless-memex
review" pointer so the next sibling tool has a home. README.md mirrors
`agent-review/README.md`.

### Phase 7 — deploy to openclaw

- `uv build` → wheel.
- `scp dist/vault_review-0.1.0-*.whl openclaw:/tmp/`.
- On the box: `uv tool install /tmp/vault_review-*.whl` (uv is already
  there).
- Verify `vault-review --help` runs on the box.
- Repoint the two recap cron entries from
  `~/vault/tools/vault-agent/vault-agent recap daily|weekly` to
  `vault-review run yesterday` / `vault-review run-weekly last-week`.
  Wrap each in a small shell wrapper (committed into the vault repo, or
  into this repo under `vault-review/deploy/`) that does
  `vault-review …` then `cd $VAULT && git add -A && git commit -m … &&
  git push` — preserving today's commit-and-push behavior without
  baking it into the tool.
- Leave the existing capture/snapshot/render cron lines untouched.

### Phase 8 — vault-agent script cleanup (Sonnet subagent OK, runs parallel with phase 4+)

Independent of the new package; touches only
`~/vault/tools/vault-agent/vault-agent`.

- Delete `run_recap` and helpers (`_git_delta_events`, `_summarize_file`,
  `_group_of`, `_render_dossier`, `_compose_telegram`, `_weekly_path_for`,
  `_ensure_weekly_file`, `_append_to_weekly`) — lines 738–1002.
- Delete the `recap` subparser and dispatch from `main()`.
- Delete the legacy `checkin` subcommand + `run_checkin` +
  `compose_morning_prompt` / `compose_evening_prompt` /
  `compose_weekly_prompt` (already retired per ADR 006).
- Delete dead `signal` references: the docstring line, `SIGNAL_DB`
  constant. Leave `import signal` (still used by `call_manifest`).
- Update the module docstring to reflect the surviving subcommands
  (`capture`, `snapshot`, `render`, `doctor`).

**Subagent brief**: "In `/home/mj/vault/tools/vault-agent/vault-agent`,
remove the recap path, the legacy checkin path, and dead `signal`
references. Specifics: [enumerated above]. Don't touch `capture`,
`snapshot`, `render`, `doctor`, or `render_workspace`. Run the script's
`--help` afterward to confirm it still parses. Report the line-count
delta and any helpers you kept because something I didn't list still
uses them." Verify the diff before commit.

## Subagent usage — summary

- **Phase 5 (tests)**: Sonnet. Mechanical translation from agent-review
  test patterns. ~30 min of work, parallelizable with phase 6.
- **Phase 8 (vault-agent trim)**: Sonnet. Independent file, well-scoped
  delete-list, easy to verify. Can run during phases 4–6.
- **Everything else**: main thread. The CLI verbs, marker regexes, and
  ISO-week parsing are small enough that handoff overhead would beat any
  parallelism win, and they're the parts where taste choices compound.

## Out of scope (filed for later)

- **Streamline agent harness code** — pull the surviving
  `~/vault/tools/vault-agent/vault-agent` (capture/snapshot/render/doctor)
  out of the vault repo into a proper dev project. Same motivation as
  this port; different shape (openclaw-coupled, jsonl-tailing).
- **PG-backed vault-review** — add a `vault_review` schema mirroring
  `agent_review`'s `daily_reports`/`weekly_reports` if/when we want
  `show`-from-DB, a viewer, or cost tracking.
- **serverless-memex-review** — sibling tool under `auto-review/` that
  does the same shape (`run today` / `run-weekly`) over the cloudflare
  memex store instead of git. Aim for the same CLI surface so all three
  tools (`agent-review`, `vault-review`, `memex-review`) share muscle
  memory.
