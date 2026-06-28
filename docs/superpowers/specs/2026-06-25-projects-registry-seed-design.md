# Projects registry seed — design (auto-review-8cw.1)

**Status:** approved 2026-06-25
**Bead:** `auto-review-8cw.1` (child of epic `auto-review-8cw` — explicit project
registry + project-state views)
**Follow-up surfaced:** `auto-review-fdj` (~/dev + vault layout consistency)

## Context

The `projects.projects` table and its grants already exist live on the
agentsview Postgres — they shipped with the schema foundation
(`auto-review-hg6.2`, migrations `0004_projects.sql` + `0005_roles.sql`). The
migration deliberately ships **no rows**: per `db/README.md` ("Registry rows and
seeds stay out of this public repo"), `projects.projects` seeds come from the
operator's local vault/dev inventory and are applied at apply-time.

So this slice is **not** schema work. It is: author a curated seed, apply it to
the live DB, and verify the rows are present and readable. CLI curation verbs,
a repeatable inventory script, and the new-project detector are explicitly
**later children** (`8cw.2`/`8cw.3`/`8cw.4`/`8cw.5`).

### Success criterion (agreed)

"**Live + queryable**": real, complete, hand-curated rows on the live DB, all
fields correctly populated for the visible set, verified readable by the
`checkin_renderer` and `auto_review_doctor` roles. No new display code.

## Mechanism — gitignored local seed, applied at apply-time

- **`db/seed/projects.seed.sql`** — the real seed, **gitignored** (carries
  absolute local home paths). Idempotent: `INSERT … ON CONFLICT (name) DO
  UPDATE SET …` over every column, so re-running re-asserts the curated state.
  Until the curation CLI lands, "edit this file + re-apply" is the interim
  curation path.
- **Committed companions** (public-repo-safe, no real paths):
  - `db/seed/README.md` — documents the mechanism and apply/verify steps.
  - `db/seed/projects.seed.example.sql` — the same shape with placeholder
    paths (`<repo-root>/…`), so the structure is reviewable in the public repo.
- **`.gitignore`** — ignore `db/seed/*`, allow-list the README + example.
- **Apply**: `db/seed/README.md` carries the authoritative, copyable apply and
  verify commands (writer `SEED_DSN` — admin/owner or the `memex_triage` curation
  role, with an inlined empty-DSN guard). This design doc deliberately does not
  duplicate the command. The apply runs in one `-1` transaction, so a bad row
  aborts the whole apply, leaving no half-state.
- **Safety gate**: applying touches the **live production DB**. The seed file is
  authored and previewed first; nothing is applied until the operator provides
  the DSN and gives an explicit go-ahead.

Rationale for local-not-committed: the README policy is explicit that seeds stay
out of the public repo. The `ops.jobs` migrations (`0007`–`0009`) technically
drifted by committing a deploy hostname, but the `projects` rows carry far more
local detail (absolute home paths), so this slice honors the stated policy
rather than the drift. (That drift, and the broader boundary, are addressed in
[`2026-06-27-infra-content-separation-design.md`](./2026-06-27-infra-content-separation-design.md).)

## Seed rows

The curated set is **11 rows** (6 active, 4 back-burner, 1 done). The actual
names, repo paths, trackers, and dates are **instance content**: they live only
in the gitignored `db/seed/projects.seed.sql` (and, at runtime, in
`projects.projects`). `db/seed/projects.seed.example.sql` shows the shape with
placeholder rows.

Membership backbone = the existing `~/vault/projects/*` convention (the
human-curated set), with a small number of additions and exclusions (e.g. a
repo that lives outside that tree; services or hosted tools with no clean local
checkout). `repo_paths` are stored absolute in the live seed.

Curation judgment calls — folding several repos into one logical project,
marking a superseded attempt `done`, excluding a project that falls outside the
membership set — are recorded as comments in the gitignored seed, next to the
rows they explain, rather than enumerated here in the public repo.

## Field conventions

- `repo_paths` — absolute (`/home/<user>/…`) in the live seed.
- `tracker_workspace` — set only for the project(s) that use a tracker (= the
  repo root, where `bd` auto-discovers `.beads/`); NULL elsewhere, satisfying
  the table's `tracker <> 'none' OR tracker_workspace IS NULL` check.
- `last_activity_at` — seeded from the **latest git commit across `repo_paths`**,
  falling back to **vault-doc mtime** for repo-less / non-git rows. The column is
  machine-maintained going forward (its documented intent).
- `status` — `active` for top-level vault projects, `back-burner` for the vault
  `back-burner/` subfolder, `done` for a superseded project. The `back-burner/`
  vault_doc path is retained regardless of status (location and status are
  independent).

## Verification (the "live + queryable" criterion)

1. `SELECT *` dump → all 11 rows present, every field as specified above.
2. Read grants confirmed via privilege checks run from the writer `SEED_DSN` (no
   need to log in as the role — matches `db/verify.sh`):
   - `has_table_privilege('checkin_renderer', 'projects.projects', 'SELECT')` → `true`
   - `has_table_privilege('auto_review_doctor', 'projects.projects', 'SELECT')` → `true`

No password provisioning is required for this slice: the seed applies with the
selected writer `SEED_DSN` (admin/owner or the `memex_triage` curation role —
see `db/seed/README.md`), and read access is verified by privilege check rather
than by logging in as the consumer roles.

## Out of scope (deferred)

- CLI curation verbs (`memex-triage project list/add/edit`) — later child; the
  `memex_triage` role already holds the S/I/U grant that anticipates it.
- Repeatable inventory/seed script + new-project detector — `8cw.5`.
- Per-project read display / renderer section — `8cw.4`.
- registry rows for projects without a clean local repo (remote-only / hosted
  tools) — deferred.
- `~/dev` folder cleanup + repo_paths↔vault_doc naming convention — `auto-review-fdj`.
