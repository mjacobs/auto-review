# vault-review

Deterministic daily and weekly recaps of what changed in an Obsidian
vault, derived from `git log` and written idempotently into the vault's
own check-in note.

**Status:** stable, in daily production since 2026-04.

No LLM, no external service — just `git log` → markdown → idempotent
file write. Sibling of [`agent-review`](../agent-review/) and
[`memex-review`](../memex-review/). See [`DESIGN.md`](./DESIGN.md) for
the full design.

## What you get

Running `vault-review today` appends a section like this to
`journal/checkins/YYYY-MM-DD.md`:

```markdown
## vault-review — 2026-05-14

_window: 2026-05-14_

### projects
- `~` `projects/auto-review/auto-review.md` — added two follow-up issues
- `+` `projects/serverless-memex/release-notes.md` — drafted the v1 cut

### journal
- `~` `journal/checkins/2026-05-13.md` — yesterday's notes
- `↻` `journal/inbox/idea.md` (renamed from `journal/inbox/2026-05-13-idea.md`)

<!-- vault-review:daily=2026-05-14 generated_at=2026-05-15T04:00:00Z -->
```

Files are grouped by top-level vault folder. The `<!-- vault-review:… -->`
marker is what makes re-runs strip-and-replace safe: hand edits anywhere
outside the marked block survive.

## Install

```bash
uv tool install .
```

Or from a wheel:

```bash
uv tool install dist/vault_review-0.1.0-*.whl
```

## Usage

```bash
# Daily recap for today / yesterday
vault-review run today
vault-review run yesterday
vault-review today          # alias
vault-review yesterday      # alias

# Daily recap for a specific date or range
vault-review run 2026-05-14
vault-review run 2026-05-10..2026-05-14
vault-review run last-week   # 7 most-recent days

# Weekly recap
vault-review run-weekly this-week
vault-review run-weekly last-week
vault-review run-weekly 2026-W19

# Inspect / remove
vault-review show 2026-05-14
vault-review show-weekly 2026-W19
vault-review reset 2026-05-14
vault-review reset-weekly 2026-W19

# Global flags
vault-review run today --dry-run   # read-only, don't write
vault-review run today --print     # also echo section to stdout
vault-review run today --dry-run --print   # both
```

## Configuration

Set via environment or `.env` in the working directory:

| Variable     | Default                 | Description                                       |
| ------------ | ----------------------- | ------------------------------------------------- |
| `VAULT_PATH` | `~/vault`               | Absolute path to the Obsidian vault git repo      |
| `TZ`         | `America/Los_Angeles`   | Timezone for "today" / "yesterday" resolution     |

## Output

Daily sections land in `journal/checkins/YYYY-MM-DD.md`, weekly sections
in `journal/weekly/YYYY-W##.md`. Both files are created with standard
frontmatter if absent. Sections are idempotent: re-running replaces the
marked block in place; human edits outside the block survive.

Marker format:

```
<!-- vault-review:daily=2026-05-14 generated_at=2026-05-15T04:00:00Z -->
<!-- vault-review:weekly=2026-W19 generated_at=2026-05-15T04:00:00Z -->
```

## Development

```bash
uv sync --group dev
uv run pytest
uv run vault-review --help
```

## See also

- [`DESIGN.md`](./DESIGN.md) — design rationale, idempotency story, denylist.
- [`deploy/`](./deploy/) — cron wrapper for unattended daily runs.
