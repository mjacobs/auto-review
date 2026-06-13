# AGENTS.md

Contributor guidance for `auto-review` — for both human readers and
AI coding agents.

## Project context

**auto-review** is a family of four sibling tools that surface
domain-specific sources for daily review. Three write a marker-bracketed
section into the daily check-in note (`<vault>/journal/checkins/YYYY/MM/YYYY-MM-DD.md`);
the fourth, `memex-triage`, is the odd one out — it delivers continuously into
a separate, human-drained inbox note.

| Tool | Source | Output |
|---|---|---|
| `agent-review` | `agentsview` Postgres | LLM-synthesized daily report → `agent_review` PG schema (`--no-vault`); the renderer emits the check-in section |
| `vault-review` | vault git history | deterministic delta recap (check-in section) |
| `memex-triage` | `serverless-memex` `/thoughts?since=<seq>` feed | exactly-once delivery into `inbox/memex.md` (rolling, action-framed) |

> **`memex-review` was dissolved 2026-06-13** (ADR 002 / beads `auto-review-hg6.4`).
> It is no longer a tool: `memex-sync` mirrors captures `serverless-memex` (D1)
> → the `memex` PG schema hourly, and the check-in renderer emits the memex
> inbox section from those rows. Likewise `agent-review` now runs `--no-vault`
> (writes only its PG row); the **renderer is the single writer** of the
> machine-owned sections (ADR 002). See `renderer/DESIGN.md`.

`vault-review` still uses the marker-bracketed idempotency story (its PG
migration is `auto-review-hg6.7`). `memex-triage` instead tracks a
monotonic-seq watermark in its own
note's frontmatter and runs continuously (desktop `*/5` timer) rather than as
a daily batch — see its [`DESIGN.md`](./memex-triage/DESIGN.md). See the
top-level [`README.md`](./README.md) for the user-facing pitch.

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

### Deployment pattern

The three daily siblings run on a Linux host with cron, the vault checked out
locally, and credentials in `~/.secrets`. (`memex-triage` is the exception —
it runs on the **desktop** as a `systemd --user` `*/5` timer; see
[`memex-triage/deploy/README.md`](./memex-triage/deploy/README.md).) Build
wheel locally, ship to the cron host, install via `uv tool`:

```bash
cd ~/dev/projects/auto-review/<tool>
uv build
scp dist/<tool>-*.whl deploy/run-<tool>-daily.sh <cron-host>:/tmp/
ssh <cron-host> 'uv tool install --reinstall /tmp/<tool>-*.whl && \
  mv -f /tmp/run-<tool>-daily.sh ~/.local/bin/ && \
  chmod +x ~/.local/bin/run-<tool>-daily'
ssh <cron-host> 'crontab -e'   # add the cron line by hand
```

> [!NOTE]
> **SSH User Configuration**: When connecting to the runner hosts (such as the LXC runner at `AUTO_REVIEW_RUNNER` or openclaw at `OPENCLAW_HOST`) via SSH/SCP, connect as the `auto-review` or `root` user. Key-based authentication is pre-configured for these accounts. Note that the local user `mj` does not exist on the runner hosts.

Stagger any new sibling by ≥30 min from the others so they don't race on
the vault git lock. Wrappers can share a single log file (e.g.
`~/.local/state/auto-review/cron.log`) or split per-tool — either works.

### Side-effect boundaries

**Confirm with the user before:**
- `crontab` edits on the cron host (or any shared host)
- Writes to a remote host's `~/.secrets` (pipe secrets via ssh stdin, never stdout)
- `uv tool install` / wrapper drops to the cron host's `~/.local/bin/`
- First-ever live write to the vault (after that, idempotent re-runs are fine)
- Cross-repo changes (`serverless-memex`, `agentsview`, etc.) — flag the boundary explicitly

**Vault git side effects depend on context:**

- **Interactive vault edits** (opening a note, running a one-off script):
  the vault has background auto-sync — files you write under the vault
  get committed and pushed by an external process. Don't `git add` /
  `git commit` the vault yourself; it'll happen.
- **Cron / timer wrappers** (`vault-review/deploy/run-recap-*`,
  `renderer/deploy/run-checkin-renderer-daily.sh`, the doctor wrapper,
  `memex-triage/deploy/run-memex-triage.sh`): the wrapper is responsible for its
  own `git add / commit / push` of the section it just wrote. This is intentional —
  it avoids races between the run finishing and the background sync picking the
  file up, and keeps the per-run audit trail (commit message names the tool +
  date) in vault history. Existing production wrappers already do this.
  **Under ADR 002 the PG-row writers lose their git path**: `agent-review`
  runs `--no-vault` and `memex-sync` touches no files; the renderer is the
  single writer that commits the machine-owned check-in sections.
  `memex-triage`'s wrapper additionally commits *only* its own
  `inbox/memex.md` and uses `--autostash`, since it runs `*/5` on a desktop
  you're actively editing in.

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
  multi-tag captures.
- **memex-review uses a linear cursor** stored at
  `<vault>/state/memex-review.yaml`, not per-item processed-state.
  Deferred items go into a backlog vault note by user convention; the
  cursor advances past them.
- **`serverless-memex` is captures-only.** Processing state lives
  vault-side. Never add a `processed_at` column or similar to memex's
  D1 — the substrate separation is load-bearing.
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
  history).

### Periodic-process registry (keep it current)

The `JOBS` list in `doctor/auto-review-doctor` is the **single source of
truth for the periodic-process stack** — every recurring job/mechanism,
its host, cadence, what it writes, and whether the doctor monitors its
liveness. The doctor both checks liveness from it *and* regenerates
`reference/auto-review/moving-pieces.md` (the "moving pieces" dashboard)
from it, so a stale row there is a stale dashboard and a blind spot.

**Any change to the periodic-job stack MUST update `JOBS`** — adding,
removing, retiring, rehosting, or rescheduling a job; standing up new
infra that runs on a schedule (even unmonitored: add it with
`monitored=False` so the coverage gap is visible). This is the one place
that drift directly caused failures to go unnoticed; treat updating it as
part of the change, not a follow-up.

### Working in this project

- Tests live alongside modules; don't file separate "write tests" issues
  — the convention here is test-as-you-go.
- File follow-ups as you discover them. The cheap habit of capturing
  "huh, I noticed X" the moment it surfaces saves real context loss
  later.

## Task tracking with `bd` (beads)

This project uses [`bd`](https://github.com/gastownhall/beads) for issue
tracking locally. The `.beads/` directory is **not committed** — task
state is maintained per machine. The workflow is a personal/AI
coordination aid; outside contributors don't need `bd` to read or
contribute to the repo.

The beads workspace here is **private-by-convention**: issues may
reference internal infrastructure (host names, IP addresses, internal
service names) that this public repo otherwise scrubs. Do **not** set
up `bd dolt push` to a public remote without first scrubbing those
issues. If a shared task store ever becomes useful, host it somewhere
that matches the trust level of its contents (e.g., on the LAN, not
on a public Dolt remote).

If you're working in this repo with `bd` installed:

```bash
bd ready                # find available work
bd show <id>            # view issue details
bd update <id> --status=in_progress
bd close <id> --reason="..."
```

Capture decision history with `bd close --reason=…` — the reason is
searchable and preserves *why* something changed.

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
