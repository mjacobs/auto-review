# Schedules & job dependencies

Source of truth for the auto-review cron **mechanism** — the nightly-chain
design, ordering rules, and change procedure. The **concrete deployment** (the
runner host, its exact crontab, and backup names) lives in the operator runbook
(the auto-review runner doc under vault `reference/homelab/services/`), which is
authoritative for the live schedule. Times below are illustrative PT (the deploy
TZ default,
`America/Los_Angeles`); `AUTO_REVIEW_RUNNER` stands in for the runner host.

The crontab is **hand-maintained**: `scripts/deploy.sh` and the doctor
deliberately never auto-edit it (AGENTS.md). To change it, edit on the box with
a backup + gated install (see [Changing the schedule](#changing-the-schedule)),
**and** update the `JOBS` registry in `doctor/auto-review-doctor` (it drives the
doctor's liveness display and regenerates `reference/auto-review/moving-pieces.md`).

## The nightly chain

Every daily job reports on **yesterday** (`D`). Since OMG-002 (2026-06-19) the
nightly jobs run as ORDERED PHASES of a single driver, `run-checkin-nightly`
(`scripts/run-checkin-nightly.sh`), invoked by ONE crontab line at `8 0 * * *`
PT. Each phase runs to completion before the next begins, so the renderer runs
because the producer FINISHED — not because a fixed clock offset guessed it
would be done (the race that broke the 06-18 note; `auto-review-bhp`, OMG-002).
`t_a → t_b` is the data window a report covers.

> **Rollout status (2026-06-19):** the driver is committed
> (`scripts/run-checkin-nightly.sh`); deploying it to `AUTO_REVIEW_RUNNER:~/.local/bin` and
> the crontab cutover — replacing the five staggered lines with the one driver
> line — are the remaining gated steps. Until the cutover lands, the box still
> runs the prior staggered layout.

| Phase (in order) | wrapper | covers `t_a → t_b` | writes | push |
|---|---|---|---|:--:|
| 1. vault-review daily | `run-recap-daily` | `D 00:00:00 → D 23:59:59` | note `D` § | ✔ |
| 2. vault-review weekly (Mondays) | `run-recap-weekly` | week `W` (Mon–Sun) | weekly note | ✔ |
| 3. agent-review (producer) | `run-agent-review-daily` | `D 00:00 → D+1 00:00` | `agent_review.daily_reports[D]` (PG) | ✗ (`--no-vault`) |
| 4. memex-sync | `run-memex-sync` | — (capture mirror; freshen) | captures (PG) | ✗ |
| 5. check-in renderer | `run-checkin-renderer-daily` | composes note `D` from PG | note `D` bracket + `ops.job_runs` | ✔ |
| 6. doctor (LAST) | `run-auto-review-doctor` | liveness snapshot | note `D+1` (own §); assesses `D` | ✔ |

Each phase is `timeout`-bounded and NON-FATAL: a failed/timed-out phase is
logged and skipped so the renderer still writes a (visible) placeholder and the
doctor still reports — a partial note beats no note.

Still on their own crontab lines (independent of the driver):

| Job | cron (PT) | role |
|---|---|---|
| `vault-sync-pull` | `*/5 * * * *` | ff-pull the vault tree |
| `run-memex-sync` | `5 * * * *` | hourly capture mirror (driver also runs it as phase 4 to freshen) |
| `run-checkin-catchup` | `0 10 * * *` | failure-only backstop (`auto-review-8vo` will thin it) |

Run order on the `D+1` morning — now a wait-chain, not timed offsets:

```
00:08  run-checkin-nightly starts (preserves the ~8-min margin after the
       agentsview push — the one edge a local wait can't block on):
         1. vault-review daily        ──┐ each phase runs to completion
         2. vault-review weekly (Mon)   │ before the next begins; the
         3. agent-review (producer)     │ renderer (5) therefore reads a
         4. memex-sync                  │ COMPLETE daily_reports[D] row,
         5. check-in renderer           │ never a missing one.
         6. doctor (LAST)             ──┘ sees every row written above.
…
10:00  check-in catch-up (hg6.11)   (failure-only backstop; mostly redundant now)
```

> **Since OMG-002 (2026-06-19) the producer→renderer race is eliminated by the
> `run-checkin-nightly` wait-chain** — the renderer is a phase that runs only
> after the producer phase completes — so this catch-up is now a **failure-only
> backstop** (`auto-review-8vo` tracks thinning/retiring it). The description
> below is the pre-orchestrator rationale.

The `10:00` slot is the producer→consumer-race **catch-up** (`auto-review-hg6.11`,
OPTION 3), the back half of buffer #2 below. It sits ~10 h after the `00:08`
producer run so a transient LLM-gateway/DB blip has had time to clear. It is
**gap-gated**: it probes Postgres read-only for `agent_review.daily_reports[D]`
and re-runs `agent-review run D --no-vault` + `checkin-renderer run D` (both
idempotent — the re-run cleanly REPLACES the placeholder) **only when that row
is missing**. On a healthy night the row is present, so it logs `no backfill
needed for D` and exits 0 — a clean no-op. Because it legitimately no-ops on most
days it is **catalogued `monitored=False`** in the doctor's `JOBS` registry (a
liveness window would false-positive every quiet day; see
`doctor/auto-review-doctor`). v0 covers the `agent-review` producer only — the
documented incident; the same placeholder reproduces for the vault/memex
sections on a pre-render blip, and broadening the catch-up to them is a
follow-up.

## Dependency graph

```
 workstation → agentsview PG (push ~23:55 + 00:00)  vault-sync (every 5 min)
        │ ~8 min margin                                    │ keeps vault current
        ▼                                                  
 ┌─ agent-review ─┐  writes daily_reports[D] (PG)          
 │                ├──HARD──► renderer ──SOFT(run last)──► doctor
 ├─ memex-sync ───┘  writes captures (PG)                  
 │                                                         
 └─ vault-review (daily & weekly)   independent: git → note; only git-serializes
```

There are **two real serial buffers** and one ordering rule — everything else is
arbitrary:

1. **agentsview push → `agent-review` (~8 min).** agent-review reads agentsview
   PG, which the workstation pushes at ~23:55 + the 00:00 `*/30` boundary. It must read
   *after* the prior day's sessions land, or the daily report is silently
   incomplete (and it won't re-run). This buffer was 21 min pre-tightening;
   trimmed to ~8. **Treat as a health threshold:** if the push isn't done in
   8 min, fix the push — don't widen the gap. ⚠ external-host dependency.
2. **`agent-review` + `memex-sync` → `renderer` (hard/data).** The renderer
   reads their PG rows; if it runs first it renders a placeholder
   (`_no agent-review report row for D_`). This is the producer→consumer race —
   `auto-review-hg6.11`, which **bit the 06-18 note (OMG-002)** when the slow
   `claude -p` haiku digest outran the fixed 11-min offset. **Resolved
   structurally by `run-checkin-nightly`:** the renderer is a *phase after* the
   producer, so the ordering is a wait, not a timed gap — the fixed-offset
   analysis here is now historical (a producer that runs long no longer races
   the renderer; it just delays it). **The catch-up (`run-checkin-catchup`, `0 10 * * *`) is the
   implemented stopgap (OPTION 3):** a transient producer failure bakes a
   permanent placeholder into note `D` (nothing re-runs), so the `10:00` job
   re-runs the producer + renderer for `D` *only when its PG row is missing* —
   giving the gateway ~10 h to recover after the `00:08` run. It's gap-gated and
   idempotent, so it's a clean no-op on every healthy night (hence
   `monitored=False` in the doctor registry). See the `10:00` entry above and
   `renderer/deploy/run-checkin-catchup.sh`.
3. **`doctor` runs last** (soft, liveness). It judges the others' freshness
   (`ops.job_runs` + section markers), so it must run after them — including the
   weekly, which is why the weekly sits at `00:08` (before the `00:22` doctor)
   instead of `10:01`. See `auto-review-hg6.12`.

Not ordered: `vault-review` (daily/weekly) shares no data with the PG chain — it
only **git-serializes** with `doctor`/`renderer` on the vault repo, and
concurrent pushes are absorbed by `pull --rebase` + one retry
(`auto-review-qgo`), so seconds of spacing suffice, not minutes.

## Why the stagger is small

The old layout spread these over ~50 min (`00:01 → 00:51`) with no real reason
beyond habit, and had the **doctor mis-slotted** at `00:31` — *before* the
`00:51` renderer — so its renderer/weekly liveness reads were always a cycle
behind (the root of the `hg6.12` weekly false-positive). The tightened layout is
~22 min, doctor last, with buffers kept only where a real dependency lives
(buffers #1 and #2 above).

## Timeline (visual)

```
 DATA DAY D ── the full calendar day every nightly report covers ──
 D 00:00                                                        D 23:59:59
 ╞═══════════════════════════════════════════════════════════════════════╡  t_a … t_b
 │            (vault commits / agent sessions / captures accrue)           │
 └──────────────────────────────────────────────────────────────────────┬─┘
                                                          window closes   ▼
   D+1, ~22-min cluster, dependency-ordered, all cover D:
     00:01 ┃▸ vault-review daily   [D 00:00:00 → D 23:59:59]  → note D
     00:05 ┃▸ memex-sync           (captures straggler sync)
     00:08 ┃▸ agent-review daily   [D 00:00:00 → D+1 00:00)   → PG row report_date=D
     00:08 ┃▸ vault-review weekly  [week W, Mon–Sun]  · Mondays only → weekly note
     00:19 ┃▸ check-in renderer    composes note D from PG    → note D
     00:22 ┃▸ doctor (snapshot)    liveness of all the above  → note D+1
            └──────── ~22 min ────────┘

 WEEKLY window (covers week W = Mon–Sun), generated the next Monday 00:08:
 Mon W ──────────────────── 7 days ──────────────────── Sun W 23:59:59 │ next Mon 00:08 ▸
   (was Sun 10:01 pre-2026-06-16 → recaps lagged a full week; see changelog)
```

Embeddable Mermaid (nightly cluster against the 24 h window):

```mermaid
gantt
    title auto-review — report window vs generation (PT)
    dateFormat YYYY-MM-DD HH:mm
    axisFormat %H:%M
    section vault-review daily
    covers day D        :done, 2026-06-16 00:00, 24h
    gen 00:01           :milestone, 2026-06-17 00:01, 0m
    section memex-sync
    sync 00:05          :milestone, 2026-06-17 00:05, 0m
    section agent-review daily
    covers day D        :done, 2026-06-16 00:00, 24h
    gen 00:08           :milestone, 2026-06-17 00:08, 0m
    section renderer daily
    covers day D        :done, 2026-06-16 00:00, 24h
    gen 00:19           :milestone, 2026-06-17 00:19, 0m
    section doctor daily
    snapshot 00:22      :milestone, 2026-06-17 00:22, 0m
```

## Changing the schedule

Edit on the box; never let tooling auto-edit it. Always back up + diff + verify:

```bash
crontab -l > ~/crontab.bak.<change>          # always back up first
# build the new crontab into /tmp/crontab.new, then:
diff ~/crontab.bak.<change> /tmp/crontab.new # eyeball it
crontab /tmp/crontab.new                      # install
crontab -l                                    # verify
# revert if needed: crontab ~/crontab.bak.<change>
```

Then update `JOBS` in `doctor/auto-review-doctor` (cadence + `hhmm`) and redeploy
the doctor so the dashboard/display match.

## Related issues

- `auto-review-hg6.11` — renderer/producer race window (the `agent → renderer`
  gap); a transient producer failure bakes a permanent placeholder. The `10:00`
  gap-gated catch-up (`run-checkin-catchup`, OPTION 3) is the implemented
  stopgap; a fuller doctor-driven / wrapper-retry self-heal (and broadening past
  the agent-review producer) remains follow-up.
- `auto-review-hg6.12` — doctor weekly false-positive. The **scheduling half**
  (doctor now runs last, weekly folded into the Monday cluster before it) is
  addressed by this layout; the **liveness half** folds into `auto-review-2vv`.
- `auto-review-2vv` — move vault-review (daily+weekly) onto `ops.job_runs`
  liveness, retiring the fragile log+marker + `reported_week_label` timing.
- `auto-review-qgo` — concurrent vault pushes; handled by `pull --rebase` +
  retry in every git-writing wrapper.

## Changelog

- **2026-06-19** — **OMG-002 fix:** the staggered nightly cron lines are
  replaced by a single ordered driver, `run-checkin-nightly`
  (`scripts/run-checkin-nightly.sh`, `auto-review-bhp`), invoked at `8 0 * * *`.
  Phases run in dependency order and WAIT, so the renderer runs after the
  producer completes (no more fixed-offset race — the 06-18 placeholder) and the
  doctor runs last structurally. `run-memex-sync` (hourly) and `vault-sync-pull`
  (`*/5`) keep their own lines; the `10:00` catch-up becomes a failure-only
  backstop (`auto-review-8vo`). Each phase is `timeout`-bounded and non-fatal.
  Crontab cutover is the gated final step (back up + diff + install).
- **2026-06-16** — Weekly cron day fixed Sunday→Monday (`1 10 * * 0` →
  `8 0 * * 1`); recaps had lagged a full week. Nightly stagger tightened
  `00:01–00:51` → `00:01–00:22`: doctor moved last (`00:31`→`00:22`), renderer
  `00:51`→`00:19`, agent-review `00:21`→`00:08` (keeping ~8 min margin after the
  agentsview push — a first cut to `00:01` was reverted as too tight for that
  feed), memex `:41`→`:05`, weekly folded into the Monday cluster
  (`10:01`→`00:08`). Backups on the box: `~/crontab.bak.weekly-day-fix`,
  `~/crontab.bak.tighten-stagger`, `~/crontab.bak.agentsview-margin`.
