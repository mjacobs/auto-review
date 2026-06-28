# `db/seed/` — apply-time registry seeds

Some tables are created empty by the migrations and seeded at **apply time**
from the operator's local machine, because their rows carry local-only detail
(absolute home paths) that does not belong in this public repo. See the parent
[`db/README.md`](../README.md) → *"Registry rows and seeds stay out of this
public repo"*.

Currently this covers the **projects registry** (`projects.projects`,
auto-review-8cw.1). The `ops.jobs` registry is seeded separately by the doctor's
`JOBS` definition (hg6.8).

## What's in here

| File | Committed? | Purpose |
|---|---|---|
| `projects.seed.sql` | **no — gitignored** | The real, curated seed. Carries absolute home paths. |
| `projects.seed.example.sql` | yes | Sanitized placeholder rows showing the exact shape. |
| `README.md` | yes | This file. |

The `.gitignore` rule ignores everything under `db/seed/` and then allow-lists
`README.md` and `projects.seed.example.sql`, so a real `projects.seed.sql` can
never be committed by accident.

## Authoring / curating the seed

Until the curation CLI verbs land (a later 8cw child), curation is **"edit the
file, re-apply"**:

1. Copy the example to the real (gitignored) seed if it doesn't exist yet:
   ```bash
   cp db/seed/projects.seed.example.sql db/seed/projects.seed.sql
   ```
2. Replace the placeholder rows with the curated set. Membership backbone is the
   `~/vault/projects/*` convention, plus explicit out-of-tree additions, minus
   projects without a clean local checkout (e.g. hosted services / remote-only
   tools). The actual additions/exclusions are recorded in the gitignored seed.
3. Field conventions (match the table in `db/migrations/0004_projects.sql`):
   - `repo_paths` — absolute (`/home/<user>/…`); plural, a project may span
     several checkouts. Empty array (`ARRAY[]::text[]`) for repo-less projects.
   - `vault_doc` — vault-relative path (`projects/…`), or `NULL` if none.
   - `tracker` — `beads` | `kata` | `none` (one or the other, never both).
   - `tracker_workspace` — set **only** when `tracker <> 'none'` (the table's
     check constraint enforces this); for beads it's where `bd` auto-discovers
     `.beads/` (usually the repo root).
   - `status` — `active` | `back-burner` | `done`.
   - `last_activity_at` — latest git commit across `repo_paths`, falling back to
     the vault-doc mtime for repo-less / non-git rows. Machine-maintained going
     forward.

The seed is **idempotent for adds and edits**: `ON CONFLICT (name) DO UPDATE`
re-asserts every curated column, so re-applying after an edit converges the
matching live rows to the file. `created_at` is excluded from the update, so
it's stamped once and preserved.

It is **upsert-only — it never deletes**. Removing or renaming a project in
`projects.seed.sql` does not retire the old row; a re-apply leaves it behind
(a rename adds a second row under the new name). Retiring a project is a
deliberate, separate step: prefer `status = 'done'` to keep the history. A true
removal — a one-off `DELETE FROM projects.projects WHERE name = '…'` — needs the
**admin/owner** DSN: the `memex_triage` curation role is granted INSERT/UPDATE
but *not* DELETE, so through `MEMEX_TRIAGE_PG_DSN` use `status = 'done'` instead.
Whole-file reconciliation (delete rows absent from
the seed) is intentionally left to the curation CLI rather than baked into the
seed.

## Apply

Applying touches the **live production DB**, so it is gated: author/preview the
seed first; only apply once a writer DSN is set and you've decided to go.

The apply needs `INSERT` + `UPDATE` on `projects.projects` (the `ON CONFLICT DO
UPDATE`). Two roles qualify:

- the **admin/owner** DSN, as `db/migrate.sh` uses; or
- the **`memex_triage`** curation role — it holds exactly the S/I/U grant that
  anticipates the curation CLI (see `db/migrations/0005_roles.sql`), so seeding
  through it is the same write-path future curation will take. Its DSN is
  `MEMEX_TRIAGE_PG_DSN` in `~/.secrets`. This is the role used in practice on
  hosts that don't carry the admin DSN.

```bash
# Pick one writer DSN: admin/owner (PG_DSN) if present, else the memex_triage
# curation role. Both apply and verify below reuse it, so a host without the
# admin DSN stays self-consistent.
# export PG_DSN='postgresql://<admin>@<pg-host>:5432/<db>'   # admin/owner; leave unset to use MEMEX_TRIAGE_PG_DSN
SEED_DSN="${PG_DSN:-${MEMEX_TRIAGE_PG_DSN:-}}"
# The :? guard is inlined into the psql arg, so an empty/unset DSN aborts the
# psql call itself — it can never fall back to libpq defaults, even pasted.
psql "${SEED_DSN:?set PG_DSN or MEMEX_TRIAGE_PG_DSN}" -X -v ON_ERROR_STOP=1 -1 -f db/seed/projects.seed.sql
```

`ON_ERROR_STOP=1` makes a SQL error fatal so a rolled-back / no-op apply can't
be missed, `-X` ignores `~/.psqlrc`, and `-1` runs the whole apply in one
transaction: a row that violates a check constraint aborts the apply and leaves
no half-state.

## Verify ("live + queryable")

```bash
# Reuses the same SEED_DSN set in the apply step above; same inlined :? guard.
# 1. all rows present, every field as curated
psql "${SEED_DSN:?set PG_DSN or MEMEX_TRIAGE_PG_DSN}" -X -c 'SELECT name, status, tracker, vault_doc, last_activity_at FROM projects.projects ORDER BY status, name;'

# 2. the consumer roles can read it (privilege check; no need to log in as them,
#    matching db/verify.sh's style)
psql "${SEED_DSN:?set PG_DSN or MEMEX_TRIAGE_PG_DSN}" -X -At \
  -c "SELECT has_table_privilege('checkin_renderer', 'projects.projects', 'SELECT');" \
  -c "SELECT has_table_privilege('auto_review_doctor', 'projects.projects', 'SELECT');"
# both -> t
```
