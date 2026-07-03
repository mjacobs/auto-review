# `db/seed/` — apply-time registry seeds

Some tables are created empty by the migrations and seeded at **apply time**
from the operator's local machine, because their rows carry local-only detail
(absolute home paths) that does not belong in this public repo. See the parent
[`db/README.md`](../README.md) → *"Registry rows and seeds stay out of this
public repo"*.

This covers two registries, seeded the same way:

- the **projects registry** (`projects.projects`, auto-review-8cw.1); and
- the **jobs registry** (`ops.jobs`, auto-review-6mf.2 / hg6.8) — the
  periodic-job moving-pieces registry, whose rows name internal hosts. Its rows
  used to be `INSERT`ed by `db/migrations/0007`–`0009`; 6mf.2 removed those
  `INSERT`s and the rows now come from this seed. See
  [`docs/superpowers/specs/2026-06-30-jobs-registry-pg.md`](../../docs/superpowers/specs/2026-06-30-jobs-registry-pg.md).

## What's in here

| File | Committed? | Purpose |
|---|---|---|
| `projects.seed.sql` | **no — gitignored** | The real, curated projects seed. Carries absolute home paths. |
| `projects.seed.example.sql` | yes | Sanitized placeholder rows showing the projects shape. |
| `jobs.seed.sql` | **no — gitignored** | The real jobs registry seed. Carries internal hostnames. |
| `jobs.seed.example.sql` | yes | Sanitized placeholder rows showing the jobs shape. |
| `README.md` | yes | This file. |

The `.gitignore` rule ignores everything under `db/seed/` and then allow-lists
`README.md`, `projects.seed.example.sql`, and `jobs.seed.example.sql`, so a real
`projects.seed.sql` or `jobs.seed.sql` can never be committed by accident.

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

## The jobs registry seed (`ops.jobs`)

The `ops.jobs` rows — the periodic-job **moving-pieces registry** (name, host,
cadence, what it writes, whether the doctor monitors it) — are content: they name
internal hosts. `db/migrations/0007`–`0009` used to `INSERT` them; 6mf.2 removed
those `INSERT`s and the rows now come from `jobs.seed.sql`. The design rationale —
where the doctor's non-content liveness *mechanics* live, degraded mode, and this
ordering — is
[`docs/superpowers/specs/2026-06-30-jobs-registry-pg.md`](../../docs/superpowers/specs/2026-06-30-jobs-registry-pg.md).

### FK-ordering caveat — apply the jobs seed BEFORE any job runs

`ops.job_runs.job_name` REFERENCES `ops.jobs(name)`, so a job's registry row must
exist before it writes its first run-row. Apply order:

```
migrate.sh              # creates ops.jobs (0001); 0007–0009 are recorded no-ops
psql -f jobs.seed.sql   # seed the registry  ← must precede any monitored job run
<jobs run>              # first ops.job_runs insert now satisfies the FK
```

A run-row written in the migrate-but-not-yet-seeded window hits the FK, but those
writes are best-effort and degrade to a no-op (`db/README.md`: "a failed/absent
write … degrades to a no-op and never crashes"), so the ordering is a correctness
**SHOULD** (monitoring is blind until the seed lands), not a crash. The projects
seed has no such ordering constraint.

### Field conventions (match `db/migrations/0001_ops.sql`)

- `name` — PK and the `job_runs` FK target; the canonical job id.
- `host` — where it runs; a placeholder in the example, a real host in the seed.
- `cadence`, `writes` — human-readable strings for the moving-pieces dashboard.
- `monitored` — does the doctor check this job's liveness? Catalogue unmonitored
  infra too (`monitored=false`) so coverage gaps show in the dashboard.
- `expected_interval` — liveness window (overdue when `now() - latest run >`
  this). **Required when `monitored=true`** and typically NULL when `false` — the
  table's `CHECK (NOT monitored OR expected_interval IS NOT NULL)` enforces the
  "monitored ⇒ has a window" half. For the schedule-aware weekly job it is only a
  sanity bound; the real weekly math lives in the doctor's code (see the design
  note).

`ON CONFLICT (name) DO UPDATE` re-asserts every registry column, so a re-apply
converges live rows to the file. `registered_at` is excluded (stamped once);
`retired_at` is left alone — retiring is a deliberate, separate step (`UPDATE
ops.jobs SET retired_at = now()`, which keeps `job_runs` history FK-valid), and a
re-apply must not silently revive a retired job. Upsert-only: it never deletes; a
removed/renamed job leaves its old row.

### Apply / verify

`ops.jobs` is **admin-curated** — no steady-state role holds INSERT/UPDATE on it
(the role model in `db/README.md`), so seed it with the **admin/owner** DSN, the
same one `migrate.sh` uses. Gated like any live-DB write.

```bash
export PG_DSN='postgresql://<admin>@<pg-host>:5432/<db>'
# -1 = one transaction (a CHECK violation aborts and leaves no half-state);
# ON_ERROR_STOP=1 makes a SQL error fatal; -X ignores ~/.psqlrc.
psql "${PG_DSN:?set PG_DSN (admin/owner)}" -X -v ON_ERROR_STOP=1 -1 -f db/seed/jobs.seed.sql

# verify: rows present (CHECK held, or the apply above would have aborted) and
# the consumer roles can read the registry (privilege check, db/verify.sh style).
psql "${PG_DSN:?set PG_DSN}" -X -c \
  'SELECT name, host, monitored, expected_interval FROM ops.jobs ORDER BY monitored DESC, name;'
psql "${PG_DSN:?set PG_DSN}" -X -At \
  -c "SELECT has_table_privilege('auto_review_doctor', 'ops.jobs', 'SELECT');" \
  -c "SELECT has_table_privilege('checkin_renderer', 'ops.jobs', 'SELECT');"
# both -> t
```
