# Infrastructure ↔ content separation — design

**Status:** approved 2026-06-27
**Related:** epic for the cleanup is filed in beads; dovetails with `auto-review-hg6`
(PG composition layer), `hg6.8` (`ops.jobs` seeding), `auto-review-8cw.1`
(projects seed — already follows the target pattern), and `auto-review-fdj`
(~/dev + vault layout).

## Problem

`mjacobs/auto-review` is a **public** repo. Its own `db/README.md` states the
policy: "no internal IPs, hostnames, or LAN details belong in any file here."
But instance content has leaked into tracked files in several places, and each
time we notice one we scrub it by hand — whack-a-mole. The root cause is that
**infrastructure (mechanism) and content (instance values) are entangled**:
design docs, code, and migrations enumerate real instances instead of
describing a mechanism that loads them.

The fix is a clean, stated boundary plus a regression guard, so the scrub
problem stops recurring.

## Principle

> The repo holds **mechanism** — schema, scripts, loaders, sanitized
> `*.example` files, and generic design docs. Every **instance value** —
> project inventory, hosts, IPs, schedules, timezone, real filesystem paths —
> lives in an operator-owned source and is loaded or seeded at apply/runtime.
> Design docs **reference** that content; they never **enumerate** it.

Classification rule for any tracked file: *if removing this line would only
matter to this one operator's machines, it is content and does not belong in
the repo.*

## Current-state map (audit 2026-06-27)

### Already separated (the boundary that works)

| Mechanism | Keeps out | Status |
|---|---|---|
| `.gitignore /db/seed/*` (+ README/example allow-list) | real `projects.seed.sql` (absolute paths) | clean — 0 commits |
| `.gitignore .env / .pgpass / .beads/ / .dolt/` | DSNs, passwords, local dolt | clean |
| beads → **internal** git remote (not GitHub) | all bd issue/comment content | never reaches the public repo |
| `~/.secrets` + `$HOME`/`<placeholder>` in `.env.example` | creds, paths | mostly clean |
| `~/.config/auto-review/` (HEALTH-WATCH-CONTEXT) | operator prose playbook | precedent for an operator content home |

### Leaks (violate the stated policy)

| # | Leak | Location(s) | Class |
|---|---|---|---|
| 1 | Real project inventory + per-project paths | the projects-registry seed **design doc** (seed-rows tables) | A — private content |
| 2 | Infra topology — hosts, RFC1918 IPs, full cron chain, TZ | `doctor/auto-review-doctor` (the `JOBS` list — canonical), `docs/schedules.md`, `renderer/DESIGN.md`, `db/README.md` | B — instance config |
| 3 | Deploy-host string in `ops.jobs` seed rows | `db/migrations/0007`–`0009` (`INSERT`s) | B — config-in-schema |
| 4 | Real home path | `vault-review/.env.example` | A — minor |

The projects registry **mechanism** (8cw.1) is already correct (gitignored
seed; consumers read PG). The leaks are the things that *bypassed* that pattern
— code/migrations/docs that hardcode instance values.

## Target architecture

The runtime source of truth is **Postgres** (consistent with `hg6`: machine
data in PG). PG rows are invisible to the public repo, so "content in PG" is
not a leak. The model:

> **PG = source of truth.** Both registries (`projects.projects`, `ops.jobs`)
> live as PG rows.
> **Gitignored `db/seed/*.sql` = bootstrap/recovery.** A fresh or rebuilt DB is
> repopulated from a local, never-committed seed (the version-controllable
> definition of the content for disaster recovery). Idempotent upsert.
> **Consumers read from PG.** No consumer re-encodes content: the doctor reads
> its job registry from `ops.jobs`, not a hardcoded list; the renderer/docs
> stop hardcoding host/IP strings.
> **Repo = mechanism.** Schema (generic migrations), loaders/apply scripts,
> sanitized `*.example` files, and design docs that reference (never list) the
> content.

This is exactly what `auto-review-8cw.1` already does for projects. The epic
brings the **jobs/topology registry** up to the same standard.

### Why not a new file-based config home (`~/.config/auto-review/`)?

Considered and rejected as the *structured* home: PG already is it. A new
config home would duplicate the runtime store. `~/.config/auto-review/` stays
only for prose (the existing playbook); the **vault** stays the human topology
narrative (`~/vault/reference/homelab/`), which the repo currently duplicates
and should instead point to.

### The monitoring-bootstrap subtlety

The doctor monitors the pipeline including PG, yet would read its job list from
PG. This is not circular: **PG-connectivity is the single bootstrapped
invariant** (its DSN is already in `~/.secrets`/`.env`). If PG is down the
doctor reports that directly; it does not need the job list to know PG should
be up. Job *definitions* change rarely; run-freshness is tracked separately in
`ops.job_runs`.

## Remediation plan

### Now (unblocks the 8cw.1 push — private-content leaks only)

1. **Scrub the projects-registry design doc**: replace the real seed-rows
   tables and path-bearing curation notes with mechanism-only text + a pointer
   to the gitignored seed and sanitized example. Update its stale "admin-only
   DSN" line to match the seed README.
2. **`vault-review/.env.example`**: drop the real `/home/<user>/vault`. Because
   pydantic-settings reads `.env` literally (no shell expansion), comment the
   override out so the code default `Path.home()/"vault"` applies, rather than
   writing `$HOME/vault` (which would coerce to a literal path). The same fix is
   applied to `agent-review/.env.example`, which had the identical `$HOME` line.

### Epic (the structural fix)

3. **Jobs registry → PG-as-truth.** Move the doctor's `JOBS` definition out of
   Python into `ops.jobs`; the doctor queries it. Provide
   `db/seed/jobs.seed.sql` (gitignored) + `jobs.seed.example.sql` (sanitized) +
   a loader, mirroring `db/seed/`.
4. **Drop content from migrations.** Remove the `INSERT`s from `0007`–`0009`
   (keep the table/schema); seed `ops.jobs` at apply time from the gitignored
   seed. (This is the `hg6.8` work.)
5. **Sanitize docs.** Move the real schedule/topology from `docs/schedules.md`
   to the vault (`reference/homelab/`); leave a generic mechanism doc that
   points there. Genericize `.223`/host strings in `renderer/DESIGN.md` and
   `db/README.md` to placeholders.
6. **Regression guard.** Add `make check-public` (or a script) that greps
   tracked files for RFC1918 IPs, known hostnames, and `/home/<user>` paths and
   fails on a hit; optionally wire it as a pre-commit/CI check. Add a policy
   line to `db/README.md` referencing this spec.

## Out of scope

- Test fixtures using a real-looking home path (synthetic, not deployed) —
  optional later cleanup, not a content leak.
- The curation CLI (edits PG directly via the `memex_triage` grant) — separate
  8cw child; the gitignored seed is the interim curation path.
- `~/dev` + vault layout reconciliation — `auto-review-fdj`.
