# Agent Instructions

This project uses **bd** (beads) for issue tracking. Run `bd prime` for full workflow context.

## Project Context

**auto-review** is a family of three sibling tools that synthesize
domain-specific sources into the daily check-in note in the Obsidian vault
(`~/vault/journal/checkins/YYYY-MM-DD.md`):

| Tool | Source | Output |
|---|---|---|
| `agent-review` | agentsview Postgres | LLM-synthesized daily report |
| `vault-review` | vault git history | deterministic delta recap |
| `memex-review` | cf-memex `/thoughts` API | deterministic capture inbox |

All three share one CLI shape and one marker-bracketed idempotency story.
The canonical project status / planning surface lives in the vault at
`~/vault/projects/auto-review/auto-review.md` — read it at the start of
any non-trivial session.

### Sibling shape

When adding or modifying a sibling, mirror `vault-review/`'s layout exactly:

```
<tool>/
  pyproject.toml          # uv-tool-installable; click + pydantic-settings
  src/<tool>/
    config.py             # pydantic-settings; VAULT_PATH, TZ, source-specific creds
    <source>.py           # pure data fetch (gitdelta.py / client.py / …)
    dossier.py            # pure render_dossier(data, …) → markdown
    vault.py              # marker-bracketed strip-and-replace writer
    cli.py                # click verbs: run, today/yesterday, show, reset, --dry-run, --print
  tests/                  # tests alongside each module
  deploy/
    run-<tool>-daily.sh   # cron wrapper: source creds, run tool, commit+push vault
    README.md             # install steps
  DESIGN.md
  README.md
```

Each section in the check-in note is marker-bracketed
(`<!-- <tool>:daily=YYYY-MM-DD generated_at=… -->`) so re-runs are
strip-and-replace; human edits outside the marker survive.

### Deployment pattern (openclaw cron)

All three siblings run on openclaw (`OPENCLAW_HOST`, user `openclaw`) under
cron. Build wheel locally, ship to remote, install via `uv tool`:

```bash
cd ~/dev/projects/auto-review/<tool>
uv build
scp dist/<tool>-*.whl deploy/run-<tool>-daily.sh openclaw@OPENCLAW_HOST:/tmp/
ssh openclaw@OPENCLAW_HOST 'uv tool install --reinstall /tmp/<tool>-*.whl && \
  mv -f /tmp/run-<tool>-daily.sh ~/.local/bin/ && \
  chmod +x ~/.local/bin/run-<tool>-daily'
ssh openclaw@OPENCLAW_HOST 'crontab -e'   # add the cron line by hand
```

Current cron lines (as of 2026-05-17 — sanity-check before relying on):
- `1 20 * * *  run-recap-daily` (vault-review)
- `1 10 * * 0  run-recap-weekly` (vault-review)
- `31 20 * * *  run-memex-review-daily` (memex-review)

Stagger any new sibling by ≥30 min from the others so they don't race on
the vault git lock. Wrappers all share `~/.local/state/vault-agent/cron.log`
for now (per-tool log split is parked future work).

### Side-effect boundaries

**ALWAYS confirm with the user before:**
- `crontab` edits on openclaw (or any shared host)
- Writes to `openclaw:~/.secrets` (and pipe secrets via ssh stdin, never stdout)
- `uv tool install` / wrapper drops to openclaw `~/.local/bin/`
- First-ever live write to the vault (after that, idempotent re-runs are fine)
- Cross-repo changes (`serverless-memex`, `agentsview`, etc.) — flag the boundary explicitly

**Vault git side effects depend on context:**

- **Interactive vault edits** (you opening a note, running a one-off
  script, etc.): the vault has background auto-sync — files you write
  under `~/vault/` get committed and pushed by an external process.
  Don't `git add` / `git commit` the vault yourself; it'll happen.
- **Cron wrappers** (`vault-review/deploy/run-recap-*`,
  `memex-review/deploy/run-memex-review-*`, future doctor wrapper):
  the wrapper is responsible for its own `git add / commit / push` of
  the section it just wrote. This is intentional — it avoids races
  between cron finishing and the background sync picking the file up,
  and keeps the per-run audit trail (commit message names the tool +
  date) in vault history. Existing production wrappers already do this.

### Secrets policy

`~/.secrets` is **per-host**. When provisioning a new host, copy the
relevant exports via a pipe so values never appear in stdout:

```bash
# on dev box:
grep -E '^export <PREFIX>_(NAME1|NAME2|…)=' ~/.secrets | \
  ssh <host> 'cat >> ~/.secrets && chmod 600 ~/.secrets'

# verify (counts only, no values):
ssh <host> 'grep -c "^export <PREFIX>_NAME1=" ~/.secrets'
```

### Design decisions worth not re-litigating

- **memex-review's daily section is an inbox for triage, not a topical
  recap.** Flat chronological + inline tag chips. Tag-grouping was tried
  early and produced 4-5× bullet duplication against LLM-enriched
  multi-tag captures. See `auto-review-115` epic for the cursor-based
  follow-on plan.
- **memex-review uses a linear cursor** (planned, see epic `auto-review-115`)
  stored at `~/vault/state/memex-review.yaml`, not per-item processed-state.
  Deferred items go into a backlog vault note by user convention; the
  cursor advances past them.
- **cf-memex is captures-only.** Processing state lives vault-side. Never
  add a `processed_at` column or similar to cf-memex's D1 — the substrate
  separation is load-bearing.
- **No common `auto-review-core` library yet.** Duplication is concrete
  (three near-identical `vault.py`s) but extraction is parked until
  ≥2 weeks of all three running produces a real refactor brief.
- **No LLM in `vault-review` or `memex-review` v1.** Deterministic
  render only. `agent-review` is the only sibling that does LLM
  synthesis (and accordingly is the only one with a Postgres cache for
  digest cost).
- **Cron wrappers own their own git push.** The "background auto-sync"
  note above is for interactive edits; cron wrappers explicitly
  `git add / commit / push` the section they wrote. Don't "fix" the
  wrappers to defer to the background sync — the explicit push is
  intentional (avoids races, preserves per-run audit trail in commit
  history). Resolved 2026-05-18 via `auto-review-jkt`.

### Working in this project

- Start any non-trivial session with `bd ready` + reading the project
  doc. Both load fast and carry most of the context the rest of this
  file doesn't.
- Tests live alongside modules; don't file separate "write tests" issues
  — the convention here is test-as-you-go.
- File follow-ups as you discover them with `bd create`. The cheap habit
  of capturing "huh, I noticed X" the moment it surfaces saves real
  context loss later.
- Use `bd close --reason="…"` to capture decision history. The reason
  is searchable and preserves *why* something changed.

---

> **Architecture in one line:** Issues live in a local Dolt database
> (`.beads/dolt/`); cross-machine sync uses `bd dolt push/pull` (a
> git-compatible protocol), stored under `refs/dolt/data` on your git
> remote — separate from `refs/heads/*` where your code lives.
> `.beads/issues.jsonl` is a passive export, not the wire protocol.
>
> See [SYNC_CONCEPTS.md](https://github.com/gastownhall/beads/blob/main/docs/SYNC_CONCEPTS.md)
> for the one-screen overview and anti-patterns (don't treat JSONL as the
> source of truth; don't `bd import` during normal operation; don't
> reach for third-party Dolt hosting before trying the default).

## Quick Reference

```bash
bd ready              # Find available work
bd show <id>          # View issue details
bd update <id> --claim  # Claim work atomically
bd close <id>         # Complete work
bd dolt push          # Push beads data to remote
```

## Non-Interactive Shell Commands

**ALWAYS use non-interactive flags** with file operations to avoid hanging on confirmation prompts.

Shell commands like `cp`, `mv`, and `rm` may be aliased to include `-i` (interactive) mode on some systems, causing the agent to hang indefinitely waiting for y/n input.

**Use these forms instead:**
```bash
# Force overwrite without prompting
cp -f source dest           # NOT: cp source dest
mv -f source dest           # NOT: mv source dest
rm -f file                  # NOT: rm file

# For recursive operations
rm -rf directory            # NOT: rm -r directory
cp -rf source dest          # NOT: cp -r source dest
```

**Other commands that may prompt:**
- `scp` - use `-o BatchMode=yes` for non-interactive
- `ssh` - use `-o BatchMode=yes` to fail instead of prompting
- `apt-get` - use `-y` flag
- `brew` - use `HOMEBREW_NO_AUTO_UPDATE=1` env var

<!-- BEGIN BEADS INTEGRATION v:1 profile:minimal hash:7510c1e2 -->
## Beads Issue Tracker

This project uses **bd (beads)** for issue tracking. Run `bd prime` to see full workflow context and commands.

### Quick Reference

```bash
bd ready              # Find available work
bd show <id>          # View issue details
bd update <id> --claim  # Claim work
bd close <id>         # Complete work
```

### Rules

- Use `bd` for ALL task tracking — do NOT use TodoWrite, TaskCreate, or markdown TODO lists
- Run `bd prime` for detailed command reference and session close protocol
- Use `bd remember` for persistent knowledge — do NOT use MEMORY.md files

**Architecture in one line:** issues live in a local Dolt DB; sync uses `refs/dolt/data` on your git remote; `.beads/issues.jsonl` is a passive export. See https://github.com/gastownhall/beads/blob/main/docs/SYNC_CONCEPTS.md for details and anti-patterns.

## Session Completion

**When ending a work session**, you MUST complete ALL steps below. Work is NOT complete until `git push` succeeds.

**MANDATORY WORKFLOW:**

1. **File issues for remaining work** - Create issues for anything that needs follow-up
2. **Run quality gates** (if code changed) - Tests, linters, builds
3. **Update issue status** - Close finished work, update in-progress items
4. **PUSH TO REMOTE** - This is MANDATORY:
   ```bash
   git pull --rebase
   git push
   git status  # MUST show "up to date with origin"
   ```
5. **Clean up** - Clear stashes, prune remote branches
6. **Verify** - All changes committed AND pushed
7. **Hand off** - Provide context for next session

**CRITICAL RULES:**
- Work is NOT complete until `git push` succeeds
- NEVER stop before pushing - that leaves work stranded locally
- NEVER say "ready to push when you are" - YOU must push
- If push fails, resolve and retry until it succeeds
<!-- END BEADS INTEGRATION -->

<!-- BEGIN BEADS CODEX SETUP: generated by bd setup codex -->
## Beads Issue Tracker

Use Beads (`bd`) for durable task tracking in repositories that include it. Use the `beads` skill at `.agents/skills/beads/SKILL.md` (project install) or `~/.agents/skills/beads/SKILL.md` (global install) for Beads workflow guidance, then use the `bd` CLI for issue operations.

### Quick Reference

```bash
bd ready                # Find available work
bd show <id>            # View issue details
bd update <id> --claim  # Claim work
bd close <id>           # Complete work
bd prime                # Refresh Beads context
```

### Rules

- Use `bd` for all task tracking; do not create markdown TODO lists.
- Run `bd prime` when Beads context is missing or stale.
- Keep persistent project memory in Beads via `bd remember`; do not create ad hoc memory files.
<!-- END BEADS CODEX SETUP -->

<!-- bv-agent-instructions-v2 -->

---

## Beads Workflow Integration

This project uses [beads_rust](https://github.com/Dicklesworthstone/beads_rust) (`br`) for issue tracking and [beads_viewer](https://github.com/Dicklesworthstone/beads_viewer) (`bv`) for graph-aware triage. Issues are stored in `.beads/` and tracked in git.

### Using bv as an AI sidecar

bv is a graph-aware triage engine for Beads projects (.beads/beads.jsonl). Instead of parsing JSONL or hallucinating graph traversal, use robot flags for deterministic, dependency-aware outputs with precomputed metrics (PageRank, betweenness, critical path, cycles, HITS, eigenvector, k-core).

**Scope boundary:** bv handles *what to work on* (triage, priority, planning). `br` handles creating, modifying, and closing beads.

**CRITICAL: Use ONLY --robot-* flags. Bare bv launches an interactive TUI that blocks your session.**

#### The Workflow: Start With Triage

**`bv --robot-triage` is your single entry point.** It returns everything you need in one call:
- `quick_ref`: at-a-glance counts + top 3 picks
- `recommendations`: ranked actionable items with scores, reasons, unblock info
- `quick_wins`: low-effort high-impact items
- `blockers_to_clear`: items that unblock the most downstream work
- `project_health`: status/type/priority distributions, graph metrics
- `commands`: copy-paste shell commands for next steps

```bash
bv --robot-triage        # THE MEGA-COMMAND: start here
bv --robot-next          # Minimal: just the single top pick + claim command

# Token-optimized output (TOON) for lower LLM context usage:
bv --robot-triage --format toon
```

Before claiming, verify current state with `br show <id> --json` or `br ready --json`. `recommendations` can include graph-important blocked or assigned work; only `quick_ref.top_picks` and non-empty `claim_command` fields represent claimable work.

#### Other bv Commands

| Command | Returns |
|---------|---------|
| `--robot-plan` | Parallel execution tracks with unblocks lists |
| `--robot-priority` | Priority misalignment detection with confidence |
| `--robot-insights` | Full metrics: PageRank, betweenness, HITS, eigenvector, critical path, cycles, k-core |
| `--robot-alerts` | Stale issues, blocking cascades, priority mismatches |
| `--robot-suggest` | Hygiene: duplicates, missing deps, label suggestions, cycle breaks |
| `--robot-diff --diff-since <ref>` | Changes since ref: new/closed/modified issues |
| `--robot-graph [--graph-format=json\|dot\|mermaid]` | Dependency graph export |

#### Scoping & Filtering

```bash
bv --robot-plan --label backend              # Scope to label's subgraph
bv --robot-insights --as-of HEAD~30          # Historical point-in-time
bv --recipe actionable --robot-plan          # Pre-filter: ready to work (no blockers)
bv --recipe high-impact --robot-triage       # Pre-filter: top PageRank scores
```

### br Commands for Issue Management

```bash
br ready              # Show issues ready to work (no blockers)
br list --status=open # All open issues
br show <id>          # Full issue details with dependencies
br create --title="..." --type=task --priority=2
br update <id> --status=in_progress
br close <id> --reason="Completed"
br close <id1> <id2>  # Close multiple issues at once
br sync --flush-only  # Export DB to JSONL
```

### Workflow Pattern

1. **Triage**: Run `bv --robot-triage` to find the highest-impact actionable work
2. **Claim**: Use `br update <id> --status=in_progress`
3. **Work**: Implement the task
4. **Complete**: Use `br close <id>`
5. **Sync**: Always run `br sync --flush-only` at session end

### Key Concepts

- **Dependencies**: Issues can block other issues. `br ready` shows only unblocked work.
- **Priority**: P0=critical, P1=high, P2=medium, P3=low, P4=backlog (use numbers 0-4, not words)
- **Types**: task, bug, feature, epic, chore, docs, question
- **Blocking**: `br dep add <issue> <depends-on>` to add dependencies

### Session Protocol

```bash
git status              # Check what changed
git add <files>         # Stage code changes
br sync --flush-only    # Export beads changes to JSONL
git commit -m "..."     # Commit everything
git push                # Push to remote
```

<!-- end-bv-agent-instructions -->
