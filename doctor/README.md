# doctor + health-watch

Cron-side health surface for the auto-review pipeline. Two tools in
this directory:

- **`auto-review-doctor`** (v0) — deterministic daily liveness check.
  Counts "did each job fire and write a section?" and surfaces the
  result as a table in today's check-in.
- **`health-watch`** — LLM-driven daily investigation against a
  bundled known-landmines playbook, gated to GREEN / NON-GREEN with
  evidence. Lives alongside the doctor until the pipeline is
  verifiably smooth.

---

## health-watch — LLM-driven daily investigation

A second daily check that complements the deterministic doctor. Where
the doctor counts "did each job fire and write a section?", the
health-watch asks Claude (optionally via an internal LiteLLM gateway)
to verify against an operator-authored known-landmines playbook and
produce an evidence-backed GREEN/NON-GREEN verdict.

Files:

| file | role |
|---|---|
| `health-watch` | executable Python (stdlib + urllib for the API call); reads context + check-ins + cron.log, calls `/v1/messages`, writes a marker-bracketed `## health-watch — YYYY-MM-DD` section into today's check-in |
| [`HEALTH-WATCH-CONTEXT.example.md`](./HEALTH-WATCH-CONTEXT.example.md) | generic playbook skeleton. Copy to `~/.config/auto-review/HEALTH-WATCH-CONTEXT.md` and edit with your real landmines. Operator-specific playbooks should not be committed to this repo. |
| `run-health-watch-daily.sh` | bash cron wrapper; sources `~/.secrets`, runs the script, commits + pushes the vault, propagates the GREEN/NON-GREEN exit code |

### Playbook location

The script resolves the playbook in this order:

1. `--context PATH` flag.
2. `HEALTH_WATCH_CONTEXT` env var.
3. `~/.config/auto-review/HEALTH-WATCH-CONTEXT.md` (recommended).
4. `~/.local/share/auto-review/HEALTH-WATCH-CONTEXT.md` (legacy).
5. The example skeleton in this directory (with a stderr warning).

The playbook is read verbatim into every LLM call, so a deployment-
specific playbook is what makes the watch useful — the more concretely
it names symptoms, log strings, and prior incidents, the more the LLM
can verify against it instead of hallucinating "looks fine."

### Cron

Cron line (08:00 PT — after the 22:01 PT doctor has settled overnight):

```
0 8 * * *  run-health-watch-daily  >> ~/.local/state/vault-agent/cron.log 2>&1
```

Required env (on the cron host, in `~/.secrets`):

- `ANTHROPIC_API_KEY` — API key sent as `x-api-key`. When
  `ANTHROPIC_BASE_URL` is set this is a gateway virtual key; otherwise
  a real Anthropic key.

Optional env:

- `ANTHROPIC_BASE_URL` — override the Anthropic SDK base URL. Point at
  an internal LiteLLM gateway to keep the shared Anthropic key off the
  cron host.
- `HEALTH_WATCH_MODEL` — default `claude-sonnet-4-6`.
- `HEALTH_WATCH_CONTEXT` — override the playbook path.
- `VAULT_PATH` — default `~/vault`.

Exit codes: 0 GREEN, 2 NON-GREEN (still wrote + pushed the section),
other = hard failure.

Local development:

```bash
ANTHROPIC_API_KEY=<key> \
ANTHROPIC_BASE_URL=<optional-gateway-url> \
./health-watch --log ~/path/to/cron.log --vault ~/vault --dry-run
```

### Promotion plan

Lives until the pipeline is verifiably smooth — roughly one week of
clean GREEN verdicts. After that, re-evaluate whether to retire it,
fold its checks into the doctor, or keep it running as a permanent
second-line check.

**Status (2026-05-31):** after the ADR-001 migration, the deterministic
`auto-review-doctor` runs on the new host (AUTO_REVIEW_RUNNER) alongside the
pipeline and is the primary liveness check. health-watch stays on
openclaw as a non-critical, experimental second-line check (migration
off openclaw was decided against — `auto-review-cq0` closed). Two known
caveats while it lives there: its `cron.log` tail now only sees
openclaw's own activity (the pipeline jobs log to .223), and its LLM
call depends on the openclaw LiteLLM gateway being up. Revisit the log
source and gateway reliability if health-watch gets serious use again.

---

## auto-review doctor (v0)

Daily health check for the auto-review sibling crons. Reads
`~/.local/state/auto-review/cron.log` + yesterday's check-in note,
renders a marker-bracketed health section, strip-and-replaces it into
today's check-in note.

**Status (2026-05-18)**: v0 wrapper script — no package, no pyproject.
Tracked as beads `auto-review-fs7` under epic `auto-review-3cf`. Promote
to a full sibling (its own `pyproject.toml`, `src/auto_review_doctor/`,
`deploy/` etc.) after ~1 week of cron runs proves the report shape is
useful.

## Files

| file | role |
|---|---|
| `auto-review-doctor` | executable Python (stdlib only); pure markdown writer |
| `run-auto-review-doctor.sh` | bash cron wrapper; runs the script + `git commit/push` the vault |
| `README.md` | this file |

## Local usage

```bash
# dry-run against your local vault, using today's PT date:
./auto-review-doctor --dry-run

# point at a specific log + date:
./auto-review-doctor --log /tmp/cron.log --date 2026-05-18 --dry-run

# write (no commit):
./auto-review-doctor --print
```

The `--vault` flag overrides `~/vault`. The `--tail` flag changes how many
log lines are scanned (default 1000).

## What it surfaces

- **Per-job liveness**: for each expected cron (vault-review daily,
  memex-review daily, agent-review daily, auto-review-doctor daily, and
  vault-review weekly on Sundays), did its most-recent success-commit
  line in the log carry a UTC timestamp that maps to today in PT?
- **Output sanity**: for each expected sibling section in yesterday's
  check-in note, is the marker present + how many non-empty lines does it
  contain? Distinguishes "ran, empty" (e.g. memex-review with 0 captures)
  from "missing entirely".
- **Failure count**: total `Traceback (most recent call last):` occurrences
  in the log tail. Currently noisy (vault-agent capture/snapshot ran for
  days before getting commented out 2026-05-18 — their tracebacks scroll
  out over the next week or so).

## Output shape

```markdown
## auto-review doctor — 2026-05-31

_4/4 jobs fired today · 0 tracebacks in log tail_

_reporting on yesterday's check-in: `journal/checkins/2026-05-30.md`_

| job | fired today | section in yesterday's check-in |
|---|---|---|
| vault-review daily | ✓ 20:01 PT | ✓ 40 lines |
| memex-review daily | ✓ 20:31 PT | ✓ 7 lines (0 captures) |
| agent-review daily | ✓ 21:01 PT | ✓ 28 lines |
| auto-review-doctor daily | ✓ 22:01 PT | ✓ 6 lines |
| vault-review weekly | — | _weekly — Sundays only_ |

<!-- auto-review-doctor:daily=2026-05-31 generated_at=2026-05-31T... -->
```

Strip-and-replace is by regex on the open heading + close marker — sibling
sections and hand-written content outside the doctor block are preserved.

## Deploy (cron host, gated on user confirmation)

```bash
# from this directory:
scp auto-review-doctor <cron-host>:~/.local/bin/auto-review-doctor
scp run-auto-review-doctor.sh <cron-host>:~/.local/bin/run-auto-review-doctor
ssh <cron-host> 'chmod +x ~/.local/bin/auto-review-doctor ~/.local/bin/run-auto-review-doctor'

# smoke test (writes today's check-in, no commit):
ssh <cron-host> 'auto-review-doctor --print'

# then add to crontab (CONFIRM WITH USER FIRST, per AGENTS.md):
#   1 22 * * *  run-auto-review-doctor  >> ~/.local/state/auto-review/cron.log 2>&1
```

22:01 PT is ≥30 min after memex-review's 20:31 daily fire, so doctor sees
both daily runs' results.

## Promotion-to-v1 trigger

After ≥1 week of cron runs:

- Was the daily section useful when reviewing check-ins? (If no — rework v0
  before promoting.)
- Did the report shape surface anything actionable that would otherwise have
  been missed? (The original motivating failure was vault-agent capture
  silently failing 288×/day — would v0 have caught that style of failure?
  Verify against the log archive.)
- Is the duplication with `vault-review` / `memex-review`'s
  marker-bracketed-section helpers concrete enough to warrant a shared
  package? (Three siblings doing similar regex work is the trigger for
  the `auto-review-core` extraction discussion in the project doc.)

If all three answers point to v1, file the promotion task under epic
`auto-review-3cf`. If only the first two, refactor doctor in place. If the
shape needs rework, iterate on v0.
