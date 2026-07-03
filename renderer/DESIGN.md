# checkin-renderer — design

## Goal

One writer. The renderer reads the per-domain PG schemas (`ops`, `memex`,
`vault_review`, `projects`, `agent_review`, `agentsview` read-only) and emits
the daily check-in note `journal/checkins/YYYY/MM/YYYY-MM-DD.md` as a
**generated view of the database** — regenerable at any time, byte-identical
for the same rows. It replaces the three marker-bracket sibling writers plus
the doctor's check-in section, deleting four `vault.py`-class writers, four
marker protocols, and three of four cron git paths along the way
(`auto-review-hg6.5`; architecture: ADR 002 /
`~/vault/brewing/2026-06-10-this-is-just-a-database.md`).

This is the resurrected `auto-review-906` assembler, now trivial because PG
holds the rows: section ordering is a list in code (closes `pfy`), idempotency
is "regenerate the file," push races vanish (one writer), and the
"human edits outside the marker" problem dissolves because the daily note
becomes wholly machine-owned — human commentary lives in the documents layer.

Success is judged the same way as the epic: **lines deleted and moving pieces
removed** (baseline 11 pieces / 6 unmonitored).

## Framing: projection, not pipeline

The sibling tools were "fetch → render → write-markdown → git." The renderer
inverts the ownership: data producers write **rows**, and one projection job
turns rows into markdown. The renderer itself fetches nothing from the
outside world — no cf-memex API, no agentsview extraction, no vault git
archaeology. If a row isn't in PG, the section says so; fixing that is the
producer's job, visible in `ops.job_runs`.

| section | source tables (verified live 2026-06-11) | rows exist today? |
|---|---|---|
| health | `ops.jobs`, `ops.job_runs` | partial (memex-sync only) |
| vault-review | `vault_review.daily_digests` (`events` jsonb) | **empty** until hg6.7 |
| memex inbox | `memex.captures` (66 rows, watermark at head, hourly sync) | **yes** |
| agent-review | `agent_review.daily_reports` (row per day since launch) | **yes** |
| projects (future, 8cw) | `projects.projects` (+ future association table) | registry only |
| weekly | `vault_review.weekly_digests` | empty until hg6.7 |

Two of five sections are renderable from live data **today**. That fact
drives the transition sequencing below.

## The seven design decisions (verdicts)

### 1. memex-review dissolves — delete it, write no rows (hg6.4)

The memex-review section is a deterministic projection of a local-day capture
window. Everything its render consumes is a `memex.captures` column:

- `_line_text`: `summary`, else first non-empty line of `content_preview` →
  `captures.summary` / `captures.content` (the sync stores the feed's
  `content_preview`; since the render takes only the first line of it, the
  preview cap is irrelevant — verified live: max content length in the mirror
  is ~156 chars and sections render one line per capture).
- `_hhmm`: `created_at` (timestamptz) in `TZ`.
- `_tag_chips`: `tags text[]`.
- window: `created_at` ∈ [date 00:00, date+1 00:00) local — same as
  `collect_for_date`.

The one piece of memex-review state, the linear cursor at
`state/memex-review.yaml`, **does not exist in the production vault**
(verified 2026-06-11), so `filter_visible` has been a no-op since the d4c
midnight-chain move (`_cursor_for_run` bootstraps to the rendered date's
midnight). Triage state lives in `memex.capture_triage` now. Nothing to
migrate.

**Verdict:** the renderer queries `memex.captures` directly; hg6.4's
"write rows" step never happens; `memex-review/` is deleted wholesale (tree,
cron line, wrapper, `~/.secrets` CF creds on `AUTO_REVIEW_RUNNER` if unused by memex-sync —
they are shared, so keep them). hg6.4's deliverable becomes the deletion
itself.

### 2. Transition sequencing — renderer bracket first, whole file last

No flag day. During transition the renderer is *one more marker writer*, with
a single contiguous bracket per note that holds **all** renderer-owned
sections:

```
<!-- checkin-renderer:begin daily=2026-06-15 -->
## memex — 2026-06-15 — inbox
…
## agent-review — 2026-06-15
…
<!-- checkin-renderer:end daily=2026-06-15 generated_at=2026-06-16T07:51:01Z -->
```

Re-runs strip-and-replace the begin/end pair (explicit pair, not the
fragile heading-to-close-marker span the siblings use). Sibling markers and
human edits outside the bracket survive. As each producer migrates, its
section moves inside the bracket and its old marker/cron/git path is deleted.

Step mapping (each step ends with a deletion — the epic's rule):

| step | renderer renders | producer change | deleted |
|---|---|---|---|
| A (this issue) | memex + agent-review sections (bracket mode) | memex-review cron removed; agent-review cron flipped to `run yesterday --no-vault` (flag already exists) | **memex-review/** entire tree + cron line + marker (hg6.4) |
| B (hg6.6) | same, but agent section from clean narrative rows | agent-review stores narrative+stats (not full section_md); inserts job_runs row | agent-review `vault.py`, marker, wrapper git path |
| C (hg6.7) | + vault-review daily section; weekly note section | vault-review writes `daily_digests`/`weekly_digests` rows + job_runs | vault-review `vault.py`, both markers, wrapper git paths |
| D (with hg6.8) | + health section; **flips daily note to whole-file regeneration** | doctor drops its check-in writer + today's-note path; doctor becomes job_runs queries + moving-pieces view | doctor's `render_section`/`strip_and_replace`/check-in cron git path; renderer's own begin/end bracket |

The whole-file flip happens only at step D, when no other writer remains.
Until then humans may still edit daily notes and their edits survive; after
the flip, daily notes carry a header comment (`<!-- generated by
checkin-renderer from PG — do not edit; human commentary goes in
documents -->`) and re-renders are destructive **by design**. The flip is a
single config change (`RENDER_MODE=full`), announced, and gated on user
sign-off like any first-ever-write.

### 3. agent-review flips on day one; vault-review waits for rows

`agent_review.daily_reports` already holds one row per day (verified live:
rows through 2026-06-10, `stats` jsonb with sessions/agents/projects/tokens/
costs, `sessions_included`, `est_cost_usd`). agent-review's CLI already has
`--no-vault` ("persist report to DB but don't write to vault"). So step A
flips its cron line to `run yesterday --no-vault` and the renderer owns the
section immediately — hg6.6 then shrinks to storage cleanup + deletions.

**The one wart:** `synth.persist_report` currently stores
`report.section_md` — the *full rendered section including the `##
agent-review — …` heading and the trailing marker comment* — in the
`narrative_md` column. Until hg6.6 fixes that, the renderer
**legacy-normalizes**: if `narrative_md` starts with `## agent-review`, reuse
it verbatim minus the trailing `<!-- agent-review:report_date=… -->` line;
otherwise (post-hg6.6 rows) render the canonical heading + summary line +
narrative + stats table from `stats` jsonb. Both paths live in
`sections/agent.py`; the legacy branch is deleted in step B's cleanup.

vault-review has no store today; `vault_review.daily_digests` is empty. Its
section **cannot** flip early — it keeps writing its marker until hg6.7
teaches it to write rows (`events` jsonb carries the per-file summaries,
which must be captured at digest time because the working tree moves on).
The renderer's `sections/vault.py` is a port of `dossier.render_dossier`'s
grouping/formatting that reads `events` jsonb instead of calling
`summarize_file` — pure function, goldens against current output.

### 4. Run model

- **Host:** the auto-review LXC (`AUTO_REVIEW_RUNNER`) — vault checkout, cron, `~/.secrets`,
  and every other periodic job already live there (ADR 001).
- **Schedule:** `51 0 * * *` PT — after the remaining writer chain (00:01
  vault-review … 00:31 doctor, both during transition) and crucially after
  the **00:41 hourly memex-sync**, so captures made between 23:41 and
  midnight are in the mirror before yesterday's window is rendered.
  agent-review's row lands ~00:23; vault_review rows (post-hg6.7) at 00:01.
- **Target date:** renders **yesterday** (D−1), like the recap siblings. The
  CLI accepts any date/range for re-renders.
- **Idempotency:** transition mode = strip-and-replace its own begin/end
  bracket; full mode = regenerate the entire file. Either way, re-running for
  the same rows is byte-stable (`generated_at` in the end marker is the only
  moving part; in full mode it lives in the header comment).
- **Git:** the renderer's **wrapper** owns commit/push of what it wrote, same
  rebase+retry pattern as today's wrappers (`git pull --rebase; git push ||
  retry`). As producers migrate they lose their git paths; at step D the
  renderer wrapper is the *only* vault-writing cron left and push races are
  structurally gone. Commit message: `checkin-renderer: daily render <ISO>`.
- **Human edits:** preserved during transition (bracket semantics). Not
  preserved after the step-D flip — that is the point; the flip is when the
  daily note stops being a surface humans write on. Weekly/monthly notes are
  different (decision 6).
- **One behavior change to flag:** today the doctor *creates* the
  current-day note at 00:31. After step D, a date's note appears once, at
  00:51 the next morning, complete. There is no "today's note" during today.
  The morning review reads yesterday's note, which now includes health.

### 5. Run-recording: grant the renderer `INSERT ON ops.job_runs`

Settles db/README open question 1. A wrapper-recorded row under a second role
means a second credential on the host for zero security gain; doctor-observed
liveness via git commits is exactly the regex-the-serialization pattern this
epic deletes. The doctor precedent already establishes "read-only across
domains + INSERT on job_runs" as a coherent privilege shape, and append-only
INSERT cannot corrupt anything the renderer reads.

**Verdict:** new migration `0006_renderer_runs.sql`:

```sql
GRANT INSERT ON ops.job_runs TO checkin_renderer;
```

(`USAGE` on `ops` is already granted.) The renderer records its own run row —
memex-sync's exact pattern: main work, then a separate connection inserts
`ok` with a summary (`{date, mode, sections: {...}, note_path}`), and a
best-effort `error` row on exception (original error still propagates; a
crashed run inserts nothing and goes overdue). Requires `ops.jobs` rows
`checkin-renderer daily|weekly|monthly` seeded at deploy (FK is the registry
enforcement).

### 6. Weekly and monthly are renderer modes — over rows, with brackets

The weekly note (`journal/weekly/YYYY-W##.md`) is **not** machine-owned and
never becomes so: its skeleton (`## projects that moved forward`, `##
synthesis`, …) is human-prose-by-design — it is a *document* with a machine
appendix. So `run-weekly` keeps section-bracket semantics permanently:
strip-and-replace a `checkin-renderer:begin/end weekly=YYYY-W##` bracket
containing the vault-review weekly dossier rendered from
`vault_review.weekly_digests.events` (post-hg6.7), creating the note with the
existing skeleton when absent (port `_default_weekly_post`). Cron: Mon 10:01
PT replaces vault-review's weekly cron at step C. The lone permanent marker
bracket in the system is a ratified exception, not drift: it marks the
machine appendix inside a human document.

Monthly (`auto-review-2l1`) is the same mode one level up: `run-monthly
YYYY-MM` writes `journal/monthly/YYYY-MM.md` (skeleton + bracket — monthly
reflections are explicitly keep-as-markdown human prose). Source: **calendar
month over daily-grain rows** — `vault_review.daily_digests` (event rollup by
group), `agent_review.daily_reports.stats` (sessions/projects/cost sums —
`SUM(est_cost_usd)` is one query), `memex.captures` counts — avoiding the
ISO-week/partial-month mismatch entirely by never touching weeklies. Cron 1st
of month 10:21 PT, `ops.jobs` row from day one. No new tool, no new marker
writer; 2l1 executes as `sections/monthly.py` + a cron line against this
design.

### 7. The doctor's check-in section is absorbed; the doctor narrows

Today the doctor is the asymmetric writer: at 00:31 on day D it writes a
health section into **day D's** note reporting on day D−1's note and the
00:0x chain that just ran — because with markdown as the database, "did the
sections land" could only be answered by regexing yesterday's note after the
chain finished.

In the PG world that question is `SELECT … FROM ops.job_runs WHERE started_at
>= <day D 00:00>` — answerable at render time, for any date. So:

- **The renderer emits the health section** into the *recap note itself*:
  note D−1, rendered at 00:51 on D, includes a health table of the runs that
  produced it (the 00:0x–00:51 chain of day D, from job_runs) plus overdue
  jobs per the README liveness query. The day-offset asymmetry disappears
  because health is computed at render time, not staged a day ahead.
- **What the renderer does not reproduce** (and deliberately drops):
  cron.log traceback mining and push-rejection counts. Tracebacks become
  `status='error'` job_runs rows with the trace in `summary` (producers
  already do this — memex-sync precedent); push rejections are moot with a
  single writer. The log-tail parsing dies with the section.
- **The doctor keeps running unchanged until step D** (its today's-note write
  never collides with the renderer's yesterday-note bracket). At step D its
  check-in writer and cron git path are deleted; what remains of the doctor
  is hg6.8's scope — liveness/cost queries, the moving-pieces view, and
  whatever alerting wants to exist — reading the same `ops` tables the
  renderer's health section reads.

Until hg6.6/6.7/6.8 put rows under every job, a PG-rendered health table
would be mostly blank — which is why health ships in step D, last.

## Rendering algorithm (daily)

1. Resolve target date D (default: yesterday in `TZ`).
2. Query, in fixed section order — the ORDER BY is a literal list:
   `[health, vault, memex, agent, projects?]` (matching today's reading
   order; `projects` is a named no-op extension point for 8cw until its
   views exist):
   - **health** (full mode only): `ops.jobs` ⨝ latest `job_runs` row per
     monitored job; runs with `started_at` in [D 00:00, render-now]
     covering the chain that built this note; overdue flags via
     `expected_interval`.
   - **vault**: `SELECT events, window_start, window_end FROM
     vault_review.daily_digests WHERE digest_date = D` → group/format port
     of `dossier.render_dossier`. Missing row → `_no digest row for D_`
     placeholder (+ visible in health).
   - **memex**: `SELECT … FROM memex.captures WHERE created_at >= D₀ AND
     created_at < D₀+1d ORDER BY created_at` (D₀ = local midnight) → port of
     memex-review's renderer (HH:MM, summary-or-first-line, tag chips,
     `0 captures` line for empty).
   - **agent**: `SELECT narrative_md, stats, generated_at FROM
     agent_review.daily_reports WHERE report_date = D` → legacy-normalize or
     canonical render (decision 3). Missing row → placeholder.
3. Compose: frontmatter identical to today's convention
   (`created/date/tags: [journal/checkin]`, `# check-in — D`).
   - **bracket mode:** load existing note (or default skeleton), strip any
     existing `checkin-renderer:begin/end daily=D` span, append the new
     bracket, write once.
   - **full mode:** write the whole file; header comment marks it generated.
4. Record the `ops.job_runs` row on a separate connection (decision 5).
5. The wrapper commits + pushes if dirty.

All section renderers are pure functions `rows → markdown` with goldens
diffed against real recent notes (e.g. `2026-06-10.md`) — the renderer must
reproduce equivalent content before it may take a section over.

## Bootstrap

- **Credentials:** `checkin_renderer` role exists (SELECT verified across all
  six schemas; write-nothing verified). Provision its password
  (`set-role-passwords.sh` / `\password`), add a `~/.pgpass` line on `AUTO_REVIEW_RUNNER`,
  and `CHECKIN_RENDERER_PG_DSN` in `~/.secrets` (role-scoped var, memex-sync
  precedent — the host's `PG_DSN` belongs to agent_review).
- **Migration:** apply `0006_renderer_runs.sql` (admin, gated on sign-off per
  db/README).
- **Registry:** seed `ops.jobs` rows for `checkin-renderer daily` (and
  weekly/monthly when those crons land) — required before the first run row
  (FK). Update the doctor's `JOBS` dataclass registry in the same change
  (AGENTS.md rule): add renderer, remove memex-review, annotate agent-review
  as rows-only.
- **No state:** the renderer is date-driven and stateless — no watermark, no
  cursor. Re-renders of any historical date are explicit CLI invocations;
  the daily cron only touches yesterday (and, post-step-D, nothing else).
- **First live write** is gated on user confirmation (AGENTS.md), preceded by
  a `--dry-run --print` golden diff against the real current note.

## CLI shape

Mirrors the sibling idioms:

```
checkin-renderer run [DATE|RANGE]        # default: yesterday (cron target)
checkin-renderer run --dry-run --print   # render to stdout, no write, no run-row
checkin-renderer run-weekly [this-week|last-week|YYYY-W##]
checkin-renderer run-monthly [last-month|YYYY-MM]
checkin-renderer show DATE               # print current note (or bracket) for DATE
checkin-renderer sections DATE           # per-section row availability (debug: what would render)
```

`RENDER_MODE` (`bracket`|`full`) comes from config; `--mode` overrides for
testing the flip. No `reset` verb — regeneration *is* the reset.

## File layout

Fifth sibling; mirrors `vault-review/` conventions (uv-installable, click +
pydantic-settings, tests alongside, thin deploy wrapper):

```
renderer/
  pyproject.toml
  src/checkin_renderer/
    config.py        VAULT_PATH, TZ, CHECKIN_RENDERER_PG_DSN, RENDER_MODE,
                     checkin_path()/weekly_dir/monthly_dir helpers (shared shape)
    db.py            psycopg3 connect; lift agent-review's pgpass fallback verbatim
    queries.py       all SQL; returns typed row dataclasses per section
    sections/
      health.py      ops rows → health table (full mode / step D)
      vault.py       daily_digests.events → dossier (port of vault-review render)
      memex.py       captures window → inbox lines (port of memex-review render)
      agent.py       daily_reports → section (legacy-normalize + canonical paths)
      projects.py    named extension point (renders nothing until 8cw)
      weekly.py      weekly_digests → weekly dossier
      monthly.py     month fold over daily-grain rows (2l1)
    compose.py       section order, frontmatter, bracket vs full assembly
    note.py          bracket strip-and-replace + whole-file writers; weekly/monthly
                     note creation with human skeletons
    runlog.py        ops.job_runs insert (separate connection, best-effort error row)
    cli.py           click verbs above
  tests/             goldens against captured real notes; per-section unit tests
  deploy/
    run-checkin-renderer-daily.sh    # render yesterday + dirty-only commit/push (rebase+retry)
    README.md                        # cron lines: 51 0 * * * daily; Mon 10:01 weekly (step C);
                                     # 1st 10:21 monthly (step D+)
  DESIGN.md
  README.md
```

## Execution plan

**Phase 0 — access + registry (gated).** `0006_renderer_runs.sql`; renderer
role password + `.pgpass`/`~/.secrets` on `AUTO_REVIEW_RUNNER`; seed `ops.jobs` renderer
row(s); verify with read-only queries against live. *Gate: admin DB access +
user sign-off per db/README.*

**Phase 1 — scaffold + sections that have rows.** Package per layout;
`config/db/queries`; `sections/memex.py` + `sections/agent.py` (with
legacy-normalize); `compose`+`note` in bracket mode; `cli run --dry-run
--print`; goldens: rendered bracket for 2026-06-10 vs the real note's memex +
agent sections (modulo heading normalization). `runlog.py` + tests.

**Phase 2 — deploy + first takeover (= step A).** Build wheel, ship to `AUTO_REVIEW_RUNNER`,
cron `51 0 * * *`; confirm one live night (bracket coexists with vault-review
marker + doctor section). Then the deletions: remove memex-review cron line,
**delete `memex-review/`** (closes hg6.4 as dissolved), flip agent-review's
cron to `--no-vault`. Update doctor `JOBS` + moving-pieces. *Gates: crontab
edits + first live write confirmations per AGENTS.md.*

**Phase 3 — vault rows + weekly (= step C, executes with hg6.7).**
`sections/vault.py` + `sections/weekly.py` against the schemas that already
exist; the moment hg6.7's producer writes rows, renderer takes the daily
vault section and `run-weekly` replaces the weekly cron; delete vault-review's
`vault.py`, markers, wrapper git paths. (hg6.6's agent cleanup — clean
narrative storage, job_runs row, delete agent vault.py — can land any time
after Phase 2, independently.)

**Phase 4 — health + the flip (= step D, with hg6.8).** `sections/health.py`
over seeded `ops.jobs`/full job_runs coverage; doctor's check-in writer +
git path deleted; `RENDER_MODE=full` flip (announced, gated);
`run-monthly` + its cron (closes the 2l1 build); delete the renderer's own
bracket machinery's transition branch. Feed results to hg6.10's
deletion audit.

## Out of scope

- **Triage surface (hg6.9).** The renderer reads `capture_triage` state for
  nothing today; the daily memex section stays a context recap of the day's
  captures regardless of triage state.
- **Project views (8cw).** Only the named `sections/projects.py` extension
  point ships; its queries/views are 8cw work.
- **serverless-memex changes.** None; the renderer never talks to D1.
- **Backfilling/regenerating historical notes.** Possible by construction
  (any DATE), deliberately not done by default — old notes may contain human
  edits from the marker era; bulk regeneration is a hand-run decision.
- **LLM anything.** Deterministic projection only; synthesis stays in
  agent-review's producer pipeline (cost work stays auto-review-8ij).
- **Alerting / dead-man checks (02w).** The renderer records runs; acting on
  missing runs is doctor/hg6.8 territory.
- **moving-pieces.md generation.** Stays with the doctor (hg6.8 makes it a
  view over `ops.jobs`); it is reference/, not journal/.

## Related

- ADR 002 (`~/vault/projects/auto-review/decisions/002-machine-data-in-postgres.md`) — the split this implements
- `db/README.md` + `db/migrations/` — schemas, role model, open question 1 (settled here)
- `memex-triage/DESIGN.md` — structural model for this doc; the triage sibling is untouched
- `auto-review-hg6` children 6.4/6.6/6.7/6.8 — producer-side steps this sequences against
- `auto-review-2l1` — monthly rollup, executed as `run-monthly` here
