# db/ — Postgres composition layer: schema foundation

The storage layer for the auto-review "Postgres composition layer" (epic
`auto-review-hg6`; architecture source:
`~/vault/brewing/2026-06-10-this-is-just-a-database.md`). Machine-written
data lives in Postgres; human-written prose lives in markdown; markdown that
machines produce is a disposable projection of the database, never a store.

Everything here targets the **existing** shared Postgres instance (the one
agentsview already uses), one schema per domain — the established pattern.

## Layout

```
db/
  migrations/
    0001_ops.sql           # ops schema: job registry + append-only job_runs
    0002_memex.sql         # memex schema: captures mirror, triage state, sync watermark
    0003_vault_review.sql  # vault_review schema: daily/weekly digest rows
    0004_projects.sql      # projects schema: curated project registry (8cw.1)
    0005_roles.sql         # least-privilege roles + grants (no passwords)
  reference/
    agent_review.sql       # READ-ONLY pg_dump snapshot of the live agent_review
                           # schema (2026-06-11) — precedent, NOT a migration
  migrate.sh               # boring runner; records versions in ops.schema_migrations
  verify.sh                # post-apply checks; nonzero exit on mismatch
  set-role-passwords.sh    # out-of-band password setting from env
```

## Schema map

| schema         | owns                                                        | written by                  | read by                          |
| -------------- | ----------------------------------------------------------- | --------------------------- | -------------------------------- |
| `ops`          | `jobs` (registry), `job_runs` (append-only), `schema_migrations` | every periodic job (runs); admin (registry) | doctor, renderer |
| `memex`        | `captures` (D1 mirror), `capture_triage`, `sync_state`      | memex_sync; triage CLI (state only) | memex-review, doctor, renderer |
| `vault_review` | `daily_digests`, `weekly_digests`                            | vault-review                | doctor, renderer                 |
| `projects`     | `projects` registry (8cw.1)                                  | triage CLI (curation surface) | doctor, renderer               |
| `agent_review` | **not created here** — pre-exists via `agent-review/migrations/001_init.sql` | agent-review        | doctor, renderer (grant is conditional) |
| `agentsview`   | **not created here** — upstream session store, reference only | agentsview pushers          | agent-review, doctor, renderer (conditional) |

## Design decisions

### Plain SQL + a shell runner, not alembic

The in-repo precedent is `agent-review/migrations/001_init.sql`: plain
idempotent SQL (`CREATE ... IF NOT EXISTS`), applied by hand with psql, no
version bookkeeping. This directory **follows** that precedent (plain SQL,
idempotent where reasonable) and **deliberately improves** it with a runner:

- `migrate.sh` applies files in filename order and records each in
  `ops.schema_migrations`, so "what has been applied where" is a query, not
  a memory. Each file is applied + recorded in a single transaction.
- No alembic: these migrations span four schemas shared by several small
  tools; nobody has a SQLAlchemy model to autogenerate from, and the only
  client dependency worth having on a cron host is `psql`. Deterministic,
  diffable SQL files are the boring choice the epic asks for.
- `ops.schema_migrations` is created by the runner itself (bootstrap), not by
  a migration — the bookkeeping table must exist before the first migration
  can be recorded.

### Idempotence policy

DDL uses `IF NOT EXISTS`; role creation is guarded by a `pg_roles` lookup
(`CREATE ROLE` has no `IF NOT EXISTS`); `GRANT` is naturally re-runnable. So
even if bookkeeping were lost, re-running the whole directory is safe.

### `ops.job_runs` is shaped by exactly two queries

Per `auto-review-hg6.8`, the doctor stops regexing markdown and becomes:

```sql
-- liveness: latest run per job vs expected cadence
SELECT j.name, r.started_at, r.status,
       (now() - r.started_at) > j.expected_interval AS overdue
  FROM ops.jobs j
  LEFT JOIN LATERAL (SELECT started_at, status
                       FROM ops.job_runs
                      WHERE job_name = j.name
                      ORDER BY started_at DESC LIMIT 1) r ON true
 WHERE j.monitored AND j.retired_at IS NULL;

-- cost: SUM over a window
SELECT job_name, sum(cost_usd)
  FROM ops.job_runs
 WHERE started_at >= now() - interval '30 days'
 GROUP BY job_name;
```

`idx_job_runs_job_started (job_name, started_at DESC)` serves the lateral;
`idx_job_runs_started` serves the cost window.

**Append-only.** A job inserts exactly one row when it finishes (the cron
wrapper inserts an `error` row on failure); rows are immutable — job roles
get `INSERT` and nothing else. A crashed or hung job inserts nothing and
simply goes overdue under the liveness query, so no `running`-row/UPDATE
protocol is needed, and the pre-existing `agent_review` role's only new
privilege is literally `INSERT ON ops.job_runs`. The FK to `ops.jobs` is
intentional: a job must be registered before its first run-row lands, which
turns AGENTS.md's "any change to the periodic-job stack MUST update the
registry" from a convention into a constraint.

`ops.jobs` replaces the doctor's `JOBS` dataclass (`moving-pieces.md` becomes
a view over it); the markdown-era fields (`hhmm`, `commit_regex`,
`marker_tool`, `marker_key`, `is_weekly`) are intentionally dropped — they
exist only to parse the serialization format this layer deletes (`is_weekly`
folds into `expected_interval`).

### The doctor's own row is the dead-man substrate (auto-review-02w)

The doctor's in-band self-liveness (a 7-day check-in lookback, auto-review-g52)
has a structural blind spot: it cannot fire while the doctor is **fully down** —
nothing runs to report the gap. To cover that "who watches the watcher" case the
doctor records **its own** `ops.job_runs` row at the end of every run (registered
as `auto-review-doctor` in `0009`; the `auto_review_doctor` role already holds the
`INSERT`). "Latest doctor row age" then becomes a queryable substrate, and the
external real-time check is one line, runnable by **any** independent process with
PG read access (the desktop, an off-host cron — anything off the doctor's host):

```sql
SELECT now() - max(finished_at)
  FROM ops.job_runs
 WHERE job_name = 'auto-review-doctor';
```

Alarm when that age exceeds a day (the job's 26h `expected_interval`). This keeps
the dead-man check **out** of the doctor without reintroducing a second check-in
writer (the contention g52 deliberately avoided) — it's a tiny `job_runs` insert,
not a new table or a second marker. The doctor writes the row via the same
stdlib `psql` subprocess seam it reads with (no psycopg dependency), best-effort:
a failed/absent write (no DSN, FK not yet applied, DB down) degrades to a no-op
and never crashes the health output. A crashed doctor writes no row at all and
simply goes overdue — exactly the signal we want.

**Residual tradeoff:** the independent checker is *itself* unmonitored (the
regress never fully closes). But a one-line SQL check on a box that is not the
doctor's host is a much smaller thing to trust than the whole doctor — acceptable
per auto-review-02w. (The doctor does **not** add a `pg_job_name` self-check to
its own `JOBS` list: that would re-create g52's watcher-flaw in-band; the row's
value is precisely as an *external* substrate.)

### memex: mirror and state are separate tables

`memex.captures` is a mirror of the cf-memex change feed (column shape =
`memex-triage`'s `Thought`); `memex.capture_triage` is PG-owned state with no
D1 counterpart. Two tables because they have two writers — the sync job and
the triage surface — and the split lets grants enforce that boundary
(memex_sync cannot flip triage state; memex_triage cannot touch the mirror).
This carries the load-bearing "serverless-memex is captures-only" substrate
separation (AGENTS.md) into the new world. The watermark lives in
`memex.sync_state` keyed by consumer name (the desktop memex-triage timer and
the D1→PG sync are independent feed consumers), preserving the
bootstrap-at-head semantics from `memex-triage/DESIGN.md`.

### vault_review rows follow the agent_review precedent

One row per period keyed by the period label (`daily_digests.digest_date`,
`weekly_digests.week_label`), structured payload in jsonb — the same shape as
`agent_review.daily_reports`. Per-file summaries are stored in the events
payload because `summarize_file` reads the vault at digest time; the working
tree moves on, so the renderer cannot recompute them later.

### Registry rows and seeds stay out of this public repo

No migration INSERTs registry/seed rows: `ops.jobs` rows name internal hosts
and `projects.projects` seeds come from the local vault/dev inventory. Both
are seeded at apply time (hg6.8 / 8cw.1 work) from the operator's machine.
This repo is public — no internal IPs, hostnames, or LAN details belong in
any file here; placeholders like `<pg-host>`/`<cron-host>` are used
throughout, matching `agent-review/deploy/README.md`. This is enforced by a
regression guard — tracked files must contain no internal IPs, hostnames, or
home-paths, checked by `make check-public` (`scripts/check-public.sh`); see
[`docs/superpowers/specs/2026-06-27-infra-content-separation-design.md`](../docs/superpowers/specs/2026-06-27-infra-content-separation-design.md)
for the mechanism/content boundary this guard protects.

## Role model

One role per writing job, least privilege. "runs: I" below = `INSERT` on
`ops.job_runs` (+ the schema `USAGE` that requires) — the append-only run
log; no job can read or rewrite history.

| role                 | used by                                    | own-domain privileges                                                                  | ops.job_runs |
| -------------------- | ------------------------------------------ | -------------------------------------------------------------------------------------- | ------------ |
| `memex_sync`         | D1 → PG capture sync (hg6.3)               | memex: `S/I/U captures`, `S/I capture_triage` (default rows only), `S/I/U sync_state`   | runs: I      |
| `memex_review`       | memex-review daily (hg6.4)                 | memex: `SELECT` all                                                                     | runs: I      |
| `vault_review_job`   | vault-review daily/weekly (hg6.7)          | vault_review: `S/I/U` both tables                                                       | runs: I      |
| `agent_review`       | agent-review daily (**pre-existing role**) | agent_review/agentsview: pre-existing grants, untouched here                            | runs: I      |
| `auto_review_doctor` | doctor (hg6.8)                             | `SELECT` across ops, memex, vault_review, projects + agent_review/agentsview (conditional) | runs: I  |
| `checkin_renderer`   | check-in renderer (hg6.5)                  | `SELECT` across ops, memex, vault_review, projects + agent_review/agentsview (conditional) | —        |
| `memex_triage`       | triage CLI/MCP (hg6.9)                     | memex: `SELECT captures/capture_triage`, `UPDATE (state, updated_at) capture_triage`; projects: `S/I/U` (curation surface; no DELETE — retire via `status`) | —    |

Naming: `vault_review_job`, not `vault_review` — roles and schemas are
separate PG namespaces (the live `agent_review` role/schema pair proves the
collision works), but new role names need not shadow schema names in grants,
`~/.pgpass` entries, and `\du`/`\dn` listings.

No role can do DDL; migrations run as the admin/owner only. New tables added
by future migrations carry their own explicit grants in that migration — no
`ALTER DEFAULT PRIVILEGES` magic.

### The pre-existing `agent_review` role

`db/reference/agent_review.sql` is a scrubbed `pg_dump --schema-only`
snapshot of the live `agent_review` schema (2026-06-11), kept as the
precedent this directory follows. What the live instance showed:

- The schema matches `agent-review/migrations/001_init.sql` exactly — both
  tables, both indexes, and the FK `session_digests.session_id →
  agentsview.sessions(id)` are all present live.
- It is owned by the admin role, with the `agent_review` service role
  granted `SELECT/INSERT/UPDATE/DELETE` on its two tables, `SELECT` on the
  `agentsview` tables, and `ALTER DEFAULT PRIVILEGES` covering future tables
  in its own schema — i.e. exactly the schema-per-domain + narrow-service-role
  pattern these migrations generalize.

`0005_roles.sql` therefore creates `agent_review` **only if missing** and
never alters it; the only privilege it adds is `INSERT ON ops.job_runs`
(plus `USAGE` on schema `ops`, without which the INSERT is unusable).

## The apply gate

> **Applying any of this against the live instance is gated on explicit user
> sign-off.** Nothing in this directory connects anywhere by itself.

- **Who**: the operator, once, with an **admin/owner** connection —
  `CREATE SCHEMA`, `CREATE ROLE`, and cross-schema `GRANT` need it. None of
  the steady-state jobs ever holds these privileges; they use their narrow
  roles above.
- **Creds**: `PG_DSN` (admin) for `migrate.sh`/`verify.sh`/
  `set-role-passwords.sh`; per-role passwords via `PGPASS_<ROLE>` env vars
  sourced from `~/.secrets` (per repo secrets policy), or interactively via
  `\password <role>`. Job hosts then get their single role's DSN in their own
  `~/.secrets` (libpq `~/.pgpass` works too — agent-review's `db.py` already
  supports passfile lookup).
- **How**:

  ```bash
  export PG_DSN='postgresql://<admin>@<pg-host>:5432/<db>'
  ./migrate.sh --dry-run    # review what would apply
  ./migrate.sh              # apply
  ./verify.sh               # schemas/tables/roles/grants; nonzero on mismatch
  ./set-role-passwords.sh   # with PGPASS_* exported
  ```

- **Threat model** (flagged in hg6.2, tracked as auto-review-60o): this
  centralizes more homelab data behind one PG credential surface. The
  per-job roles are the mitigation — a leaked cron-host credential exposes
  one schema's write path, not the instance.

## Open questions

1. **Renderer liveness.** The renderer is itself a periodic job, but the
   design (per hg6.2 scoping) keeps `checkin_renderer` strictly SELECT-only,
   so it cannot record its own `job_runs` rows. Options: let its cron wrapper
   record the run under a second role, or grant the renderer `INSERT` on
   `ops.job_runs` like the doctor has. Decide at hg6.5.
2. **Full content vs preview.** The change feed client falls back
   `content_preview → content`; whether the worker returns full content for
   the sync job (vs a capped preview) needs checking against serverless-memex
   before hg6.3 — `memex.captures.content` stores whatever the feed delivers.
3. **Capture deletion propagation.** The seq feed has no tombstones; a D1
   delete currently never reaches the PG mirror. Probably fine (deletes are
   rare), but decide before treating the mirror as authoritative.
4. **Dead-man substrate (auto-review-02w).** RESOLVED: the doctor now records
   its own `ops.job_runs` row each run (registered in `0009`), so "latest
   doctor row age" is the substrate — see "The doctor's own row is the dead-man
   substrate" above. A separate `ops.heartbeats` table was considered and
   dropped as speculative (per hg6.8 "a heartbeat row in job_runs is the natural
   deadman substrate"). What stays open is only *deploying* an independent
   checker (the one-line SQL on the desktop / an independent host); that checker is
   itself unmonitored, an accepted residual.
5. **`job_runs.status` vocabulary.** `ok/error` only. `running` went away
   with the append-only design (no row to update); a `skipped` state (e.g.
   weekly jobs on non-Mondays) was considered and deferred — the liveness
   query handles weekly cadence via `expected_interval`, and no current
   consumer needs `skipped`.
6. **`ops.jobs` seeding + registry editing.** Seed script from the doctor's
   `JOBS` registry is hg6.8 work; who curates the registry after that
   (admin-only today) is open.
7. **Triage metadata.** A free-text note / filed-to target on
   `capture_triage` was considered and deferred until the triage surface
   (hg6.9) shows it's needed.
8. **Capture → project association** (8cw.2) gets its own migration once the
   triage surface design lands; `0004_projects.sql` deliberately does not
   speculate on its shape.
9. **Password logging caveat.** `ALTER ROLE ... PASSWORD` can appear in the
   server log if `log_statement` is permissive; use `\password` interactively
   if that matters on this instance.
10. **Grants on future agent_review/agentsview tables.** The doctor/renderer
    read grants on those two pre-existing schemas use
    `GRANT SELECT ON ALL TABLES`, which is point-in-time: a table added to
    either schema later is not covered (this directory deliberately does not
    touch other schemas' `ALTER DEFAULT PRIVILEGES`). Re-running `0005`'s
    grants — or a per-table grant in the migration that needs it — covers new
    arrivals.
