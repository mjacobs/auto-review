# Jobs registry → Postgres — liveness mechanics, degraded mode, seed order

**Status:** draft 2026-07-02 — reviewable, pre-implementation
**Related:** implements the epic
[`2026-06-27-infra-content-separation-design.md`](./2026-06-27-infra-content-separation-design.md)
(*Epic* steps 3–4) and beads `auto-review-6mf.1` (this note) / `auto-review-6mf.2`
(dropping the registry `INSERT`s from migrations `0007`–`0009`). Sits on top of
`db/migrations/0001_ops.sql` (`ops.jobs`), the `db/seed/` projects-seed pattern
(`auto-review-8cw.1`), and the `JOBS`/`Job` registry in `doctor/auto-review-doctor`.

## Problem

The epic moves the jobs registry out of the doctor's in-code `JOBS` list into
`ops.jobs` (PG = source of truth) so hosts/IPs/schedules stop leaking into this
public repo. But `JOBS` today is **two different things wearing one dataclass**,
and only one of them is content:

- **Registry** — `name`, `host`, `cadence`, `writes`, `monitored`
  (+ `expected_interval`, `retired_at`). This is the moving-pieces dashboard,
  and it is *content*: rows name internal hosts and schedules (a runner host
  with its IP suffix, a workstation name, …). → belongs in `ops.jobs`, which
  `0001` already shapes exactly for it.
- **Liveness mechanics** — the fields the doctor *executes* to decide "overdue":
  the **marker path** (`hhmm`, `commit_regex`, `marker_tool`, `marker_key`),
  the **PG path** (`pg_job_name`, `pg_interval_hours`), and the **PG-weekly
  path** (`pg_weekly`, `pg_weekly_dow`, `pg_weekly_hhmm`, `pg_grace_hours`).
  `ops.jobs` holds *none* of these — except the flat window, since
  `expected_interval` already subsumes `pg_interval_hours`.

Three questions block the refactor. This note decides them; the doctor code
change is left to the review that follows (do **not** rewrite the doctor here).

## Decision 1 — where the liveness mechanics live: **hybrid**

**`ops.jobs` is the source of truth for the registry; the doctor keeps a small
in-code map of liveness mechanics keyed by `ops.jobs.name`.** Reject extending
the `ops.jobs` schema to hold the regexes/weekly params.

Field-by-field home:

| `Job` field(s) | kind | new home |
|---|---|---|
| `name` | registry (PK) | `ops.jobs.name` |
| `host`, `cadence`, `writes` | registry — **content** (names hosts/schedules) | `ops.jobs` |
| `monitored`, `retired_at` | registry | `ops.jobs` (already there) |
| `expected_interval` (≡ `pg_interval_hours`) | liveness *data*, leak-free | `ops.jobs.expected_interval` (already there) |
| `hhmm`, `commit_regex`, `marker_tool`, `marker_key` | liveness *mechanics* (marker path) | in-code mechanics map |
| `pg_weekly`, `pg_weekly_dow`, `pg_weekly_hhmm`, `pg_grace_hours` | liveness *mechanics* (weekly branch) | in-code mechanics map |
| `pg_job_name` | join key | drop — post-refactor the key *is* `ops.jobs.name` |

The map is `{ job_name: LivenessSpec }`. A job **absent** from the map uses the
default liveness — "latest `ops.job_runs` row younger than
`ops.jobs.expected_interval`?" (the common case: every plain PG-writer). Only
the two special shapes need an entry: **marker-path** jobs (the doctor's own
self-row; the legacy path) and the **schedule-aware weekly** job. `expected_interval`
stays authoritative in `ops.jobs` — the code map never duplicates it, it only
holds the *non-data* mechanics.

**Why hybrid, not "extend `ops.jobs`":**

1. **These fields are code, not content.** A `commit_regex` is a compiled
   `re.Pattern` the doctor runs; the weekly branch is a code path selected by a
   boolean. Storing a regex in a `text` column means the doctor recompiles
   operator-editable regexes at runtime — a foot-gun (a bad seed regex breaks
   liveness) that widens what "content" can inject into a code path. The
   mechanism/content boundary the epic draws puts executable logic in the repo.
2. **They leak nothing** — so there is no reason to hide them in PG. Apply the
   epic's classification rule ("if removing this line would only matter to *this
   operator's* machines, it is content"): `host = "<runner-host> (<ip-suffix>)"`
   matters to one operator → content → PG. A commit-line regex, or
   `weekday = Monday`, matters to *any* deployment of this stack → mechanism →
   code. Same rule, opposite answers — which is exactly why they split.
3. **Schema churn for one-off fields.** `pg_weekly_*`/`pg_grace_hours` are used
   by a *single* job (the weekly recap). Typed columns + a widened `CHECK`
   surface in `0001` to carry fields one row uses is a poor trade; the flat
   window (`expected_interval`), the one clean liveness datum, is already the
   only liveness field in the table, and that is the right amount.
4. **The marker path is being deleted.** Keeping its regexes in code keeps the
   deletable thing deletable — when the last marker job is gone, delete a map
   entry, not a migration + a column.

**Bonus: the split makes degraded mode fall out for free.** The in-code map is
*also* the enumeration of the marker-path jobs, and marker-path liveness reads
`cron.log` + check-in markers, **not** PG. So the PG-independent checks (the
doctor's own self-liveness) stay PG-independent — see Decision 2. PG-path jobs
are enumerated by querying `ops.jobs WHERE monitored AND retired_at IS NULL`
(the `db/README.md` liveness query); marker-path jobs are enumerated by the code
map. Clean partition: **who to check via PG** lives in PG; **who to check via
markers, and how** lives in code.

## Decision 2 — degraded mode (PG unreachable): **skip the projection, never fabricate**

PG-connectivity is the single bootstrapped invariant (`db/README.md` →
"monitoring-bootstrap subtlety"); the doctor must still produce a health run on
a PG-less box, as it does today.

**Rejected: a built-in default registry compiled into the script.** That
re-embeds `host`/IP/schedule strings back into Python — it *reintroduces the
exact leak the epic exists to remove*. Non-starter.

**Chosen:** when the registry can't be read (no DSN / no `psql` / PG down):

- **The moving-pieces dashboard is skipped, not fabricated.** The doctor leaves
  the previously generated `moving-pieces.md` in place (it is a *disposable
  projection of the database* — `db/README.md` opening — stamped with its own
  `generated_at`) and emits a health line: *"registry unavailable (PG down) —
  moving-pieces not regenerated."* It never reconstructs the registry from a
  stale in-code copy.
- **PG-path liveness already degrades to "unknown"** (per AGENTS.md: no
  DSN/psql → PG jobs shown as unknown). Unchanged — liveness for those jobs is
  inherently a PG question, and *PG itself is monitored*, so "PG down" is already
  reported loudly. There is nothing to add and no value in also faking the
  dashboard.
- **The doctor's core health output does not touch the registry** — self-liveness
  (`doctor_self_liveness`, the 7-day check-in lookback), `cron.log` traceback
  scanning, and the marker-path self-check all run from code / the check-in dir,
  not from an `ops.jobs` read. So the doctor still runs and still reports on a
  PG-less box; the *only* thing that degrades is the registry-derived
  dashboard — which is precisely the piece that is now content-in-PG.

Rationale in one line: a projection you can't compute (source down) is simply
not regenerated this run; the last one stands, and PG-down is surfaced on its
own. That is strictly better than fabricating from a compiled-in copy (a leak)
or crashing (loses the whole health run).

## Decision 3 — FK-seeding order: **migrate → seed jobs → jobs run**

The `ops.job_runs.job_name → ops.jobs.name` FK requires a job's `ops.jobs` row
to exist *before* that job writes its first run-row. The old `0007`–`0009`
`INSERT`ed those rows *as part of migrate*, so the ordering was implicit. Once
the rows move to the (separately applied) `db/seed/jobs.seed.sql`, the operator
gets a two-step apply and an explicit ordering constraint:

1. **`migrate.sh`** — creates `ops.jobs` (`0001`) plus all schemas/roles/grants.
   `0007`–`0009` are now recorded no-ops (comment-only), so migrate inserts no
   registry rows.
2. **Seed jobs** — `psql -f db/seed/jobs.seed.sql` (idempotent upsert into
   `ops.jobs`). **Must run before any monitored job's first run.** The projects
   seed (`projects.seed.sql`) is independent and may be applied in either order
   relative to this one.
3. **Jobs run** — the first nightly/cron run of any job now finds its `ops.jobs`
   row, and its `ops.job_runs` insert satisfies the FK.

**Edge case (not a crash):** a job that writes `ops.job_runs` in the
migrate-but-not-yet-seeded window hits the FK. But those writes are
**best-effort and degrade to a no-op** (`db/README.md`: "a failed/absent write
— no DSN, FK not yet applied, DB down — degrades to a no-op and never crashes")
— the doctor's own dead-man row and any cron-wrapper `error` row simply don't
land until the seed does. So the ordering is a **correctness SHOULD** (monitoring
is blind until the seed lands), not a hard failure.

**Migration-history caveat (as documented in the rewritten `0007`–`0009`):**
rows a *prior* `migrate.sh` run already committed to a live DB **stay put** —
removing the `INSERT` from the file does not un-apply them, and `migrate.sh`
skips already-recorded versions so it will not re-run these files. This change
only stops committing **new** content rows going forward; the live registry is
reconciled by applying (idempotently) `jobs.seed.sql`, whose upsert re-asserts
every registry column. The `ops.jobs` **table** (`0001`) is untouched.

## Summary of the boundary

| piece | lives in | why |
|---|---|---|
| registry rows (`name`/`host`/`cadence`/`writes`/`monitored`/`expected_interval`/`retired_at`) | `ops.jobs` (PG), seeded from gitignored `db/seed/jobs.seed.sql` | content — names internal hosts/schedules |
| marker-path mechanics (`commit_regex`/`marker_*`/`hhmm`) | in-code map, keyed by `name` | executable code; leak-free; being retired |
| weekly-aware mechanics (`pg_weekly*`/`pg_grace_hours`) | in-code map, keyed by `name` | executable code; one job; leak-free |
| moving-pieces dashboard | projection of `ops.jobs`; skipped when PG down | disposable projection, never a store |

## Out of scope (left to the follow-up doctor refactor)

- The actual doctor edits: dropping the registry fields from `Job`, reading the
  registry from `ops.jobs`, and defining the `LivenessSpec` map. This note fixes
  the *shape*; the human review that follows lands the code.
- `docs/schedules.md` / `renderer/DESIGN.md` scrubbing (epic step 5) and the
  `make check-public` regression guard (epic step 6) — separate epic children.
- Whether the weekly job's schedule params should eventually derive from a
  parsed `cadence` string instead of a hand-set map entry — a later
  simplification, not needed for the separation.
