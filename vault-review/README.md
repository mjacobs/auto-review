# vault-review

Daily and weekly narrative recaps of vault activity, derived deterministically
from `git diff` over the Obsidian vault, written idempotently into the vault.

Sibling of [agent-review](../agent-review/). See [DESIGN.md](./DESIGN.md)
for design rationale and [docs/history/PLAN.md](./docs/history/PLAN.md)
for the original implementation log.

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

| Variable | Default | Description |
|---|---|---|
| `VAULT_PATH` | `~/vault` | Absolute path to the Obsidian vault git repo |
| `TZ` | `America/Los_Angeles` | Timezone for "today" / "yesterday" resolution |

## Output

Daily sections land in `journal/checkins/YYYY-MM-DD.md`, weekly sections in
`journal/weekly/YYYY-W##.md`. Both files are created with standard frontmatter
if absent. Sections are idempotent: re-running replaces the marked block in
place; human edits outside the block survive.

Marker format:
```
<!-- vault-review:daily=2026-05-14 generated_at=2026-05-15T04:00:00Z -->
<!-- vault-review:weekly=2026-W20 generated_at=2026-05-15T04:00:00Z -->
```

## Development

```bash
uv sync
uv run pytest
uv run vault-review --help
```
