# auto-review doctor v0 — Review Prep (2026-05-25)

_cf8 review window. Doctor deployed 2026-05-18, cron `1 22 * * * run-auto-review-doctor`,
first fire 2026-05-18 22:01 PT. Expect ~7 daily sections in
`vault/journal/checkins/2026-05-18.md` through `2026-05-24.md`._

YOU DO NOT NEED THIS REPO TO DO THE REVIEW — all reads are against your
local vault and cron.log on openclaw. This document is the script;
run through it top-to-bottom and record verdicts inline or in beads.

---

## Part A — Reviewer checklist (cf8's 4 questions → concrete local actions)

### Q1 — Utility: Was the daily section useful when reviewing check-ins?

**Local action**: Open each of the 7 check-in files:

```
vault/journal/checkins/2026-05-18.md  (first fire — doc likely minimal)
vault/journal/checkins/2026-05-19.md
vault/journal/checkins/2026-05-20.md
vault/journal/checkins/2026-05-21.md
vault/journal/checkins/2026-05-22.md
vault/journal/checkins/2026-05-23.md
vault/journal/checkins/2026-05-24.md
```

For each, locate the `## auto-review doctor — YYYY-MM-DD` block and answer:
- Did you actually read this section during your check-in review that day (not just notice it existed)?
- Did any table row change what you did next (you investigated something, confirmed a job was healthy, or noticed something odd)?

**Pass criterion**: ≥4/7 sections were actively engaged with (not skimmed or ignored). If all 7 were ignored or you cannot recall, the format needs rework before promotion — record that in Q4.

---

### Q2 — Signal: Did the report shape surface anything actionable?

**Local action**: For each of the 7 sections, note the summary line
(`_N/N jobs fired today · N tracebacks in log tail_`) and any `❌` rows.
Then cross-check against what you know actually happened those days:

- If all rows are ✓ and zero tracebacks: confirm jobs did actually run.
  Spot-check by grepping cron.log for one commit line per job per date.
- If any `❌` rows: did you investigate? Was the underlying job broken?
- Traceback count trend: was it declining across the 7 days (old vault-agent
  lines scrolling out) or did it spike unexpectedly on any day?

```bash
# on openclaw — confirm a specific day's vault-review fire:
grep "vault-review: daily recap" ~/.local/state/vault-agent/cron.log | tail -10

# check traceback trend (line count per day is approximate):
grep -c "Traceback (most recent call last):" ~/.local/state/vault-agent/cron.log
```

**Pass criterion**: At least one non-trivial finding attributable to the doctor
within the 7-day window (a detected problem, a confirmation that averted
unnecessary investigation, or a correctly-low traceback count). All-green is
fine as a finding — the question is whether you *verified* it rather than
assumed it.

---

### Q3 — Abstraction: Is the section-regex duplication concrete enough for a shared package?

**Local action**: Compare these three functions side by side:

| location | function |
|---|---|
| `doctor/auto-review-doctor:81` | `section_info()` + `strip_and_replace()` |
| `vault-review/src/vault_review/vault.py` | equivalent marker logic |
| `memex-review/src/memex_review/vault.py` | equivalent marker logic |

Look for near-identical regexes, strip-and-replace logic, or `ensure_checkin()`
equivalents. Count distinct functions that are ≥90% identical across ≥2 siblings.

**Pass criterion**: ≥2 non-trivial near-identical functions across siblings →
file `auto-review-core` extraction under epic `auto-review-3cf`. If only 1
function or the overlap is trivial (e.g. the marker pattern itself), park it —
the README already notes "≥2 weeks of all three running" as the extraction
trigger.

---

### Q4 — Shape: Does v0 need iteration before promotion, or is the shape stable?

**Local action**: After reading all 7 sections, note any "I wish it told me X"
moments. Specific things to check:

- **Traceback count calibration**: is it still noisy (high counts from
  scrolling-out vault-agent lines), or has it settled to near-zero by
  2026-05-24? If still noisy on day 7, that's a v0 iteration item.
- **Table width**: does the three-column table scan comfortably, or is the
  `section in yesterday's check-in` column too sparse to be useful?
- **`_reporting on yesterday's check-in: …`_ note**: helpful orientation or
  noise?
- **Weekly row**: vault-review weekly fires Sundays only. 2026-05-19 is a
  Tuesday, so the first Sunday in the window is 2026-05-19 (no — that's
  Tuesday). Actually: 2026-05-24 is a Sunday. Check that day's section to
  verify the weekly row behaved correctly. The code has a known TODO:
  "verify after first weekly fire" (`auto-review-doctor:147`).

**Pass criterion**: No unresolved "I wish it told me X" moments AND the weekly
row on 2026-05-24 rendered correctly → shape is stable. Any moments → record
them; they gate promotion.

---

## Part B — Would v0 have caught the 815/cgd failure?

### Background

Issues 815 and cgd both concern **vault-agent capture/snapshot**: the tool
ran ≈288 times/day, each run produced a `Traceback (most recent call last):`
in cron.log and exited 0. No data was actually captured. The silent failure
went unnoticed for multiple days because the process appeared to succeed to
the scheduler and no downstream check surfaced the data absence.

The cron.log note in `doctor/README.md:139` confirms: "vault-agent
capture/snapshot ran for days before getting commented out 2026-05-18 —
their tracebacks scroll out over the next week or so."

### What v0 monitors (and does not)

v0 watches three signals (source: `auto-review-doctor:113-156`):

| signal | how it works | what it catches |
|---|---|---|
| sibling job liveness | latest commit line in log matching `JOBS[].regex` with today's PT date | job-level fire/no-fire |
| section presence | marker `<!-- {tool}:daily=YYYY-MM-DD … -->` in yesterday's check-in | section written vs. absent |
| traceback count | `count_tracebacks()` — counts `Traceback (most recent call last):` in last 1000 lines | any process traceback in the tail |

**vault-agent capture is NOT in `JOBS`.** v0 only monitors
`vault-review daily`, `memex-review daily`, and `vault-review weekly`.
vault-agent is upstream infrastructure, not a monitored sibling.

### Predicted signal during the 815/cgd window

| signal | value during 815/cgd failure | expected doctor output |
|---|---|---|
| vault-review daily fire | ✓ fires independently | `✓ 20:01 PT` |
| vault-review section present | ✓ section written (delta may be stale/empty) | `✓ N lines` |
| memex-review daily fire | ✓ fires independently | `✓ 20:31 PT` |
| traceback count | HIGH — 288 runs/day × ~6 lines/traceback ≈ 1728 lines/day; 1000-line tail covers ~0.6 days → ~172 tracebacks counted | `172 tracebacks in log tail` (approx) |

### The test — run it locally

```bash
# On openclaw: find the date range when vault-agent capture was traceback-ing.
# The doctor would have been running from 2026-05-18; look at the tail for that day:
grep -n "Traceback" ~/.local/state/vault-agent/cron.log | head -5
# Note the earliest traceback date.

# Then open vault/journal/checkins/<that-date>.md and find:
#   _reporting on yesterday's check-in: ..._
#   N tracebacks in log tail
# Compare N to the ~172 estimate above.
```

### Pass/fail criterion

**Pass — v0 partially catches it**:
The doctor section for dates overlapping with the 815/cgd window shows a
traceback count ≥ 50, AND seeing that number would have prompted investigation
(i.e. you would NOT have dismissed it as expected noise on that day).

**Fail — v0 does not catch it**:
Either (a) the traceback count was nonzero but you treated it as expected
noise (the README explicitly calls it "currently noisy" during scroll-out),
OR (b) the tracebacks had already scrolled out of the 1000-line tail, giving
a false-zero count while the failure was ongoing.

### Structural verdict

v0 has a **structural gap** for this failure class:

1. It monitors sibling job liveness but not upstream data-collection jobs
   (vault-agent capture, serverless-memex API health).
2. The traceback count signal IS present and would have been HIGH, but v0's
   own README primes you to expect noise — making the signal ambiguous exactly
   when it's most needed.
3. vault-review's section line count (`✓ 40 lines` vs. `✓ 2 lines`) could
   implicitly signal stale/empty captures, but v0 has no baseline to
   distinguish a slow vault day from a broken capture day.

**v1 implication** (capture for Part C / D if decision goes that way):
To catch silent 815/cgd-class failures, v1 needs one or more of:
- A `JOBS` entry or separate check for vault-agent's *data presence*
  (e.g. check if vault-review's section is suspiciously short compared
  to a rolling baseline).
- A "consecutive identical line count" anomaly detector.
- Explicit landmine entry in the `health-watch` playbook
  (`HEALTH-WATCH-CONTEXT.md`) naming the 288×/day traceback pattern.

---

## Part C — v1 Promotion Checklist

Use only if Part A verdict is "promote." File the promotion task under epic
`auto-review-3cf` and work through this list.

### Target directory layout (mirrors sibling shape from `AGENTS.md`)

```
doctor/
  pyproject.toml                    # uv-tool-installable; click + pydantic-settings
  src/auto_review_doctor/
    __init__.py
    config.py                       # pydantic-settings: LOG_PATH, VAULT_PATH, TZ, TAIL_LINES
    log.py                          # tail_lines(), count_tracebacks(), latest_match()
    assess.py                       # JobReport dataclass, JOBS registry, assess_jobs()
    render.py                       # render_section()
    vault.py                        # strip_and_replace(), ensure_checkin(), iso_week_path()
    cli.py                          # click: run, show, --dry-run, --print, --date, --log, --vault
  tests/
    test_log.py
    test_assess.py
    test_render.py
    test_vault.py
  deploy/
    run-auto-review-doctor.sh       # copy of current wrapper, path updated for uv-installed bin
    README.md
  DESIGN.md
  README.md
```

### Promotion checklist

- [ ] `pyproject.toml`: `[project.scripts] auto-review-doctor = "auto_review_doctor.cli:main"`,
      deps = `click`, `pydantic-settings`
- [ ] Split `doctor/auto-review-doctor` (single file, 289 lines) into modules above
- [ ] `config.py`: env vars `DOCTOR_LOG_PATH`, `VAULT_PATH`, `DOCTOR_TAIL_LINES`, `TZ`
      override CLI defaults; no secrets required
- [ ] All existing CLI flags preserved: `--log`, `--vault`, `--date`, `--tail`,
      `--dry-run`, `--print`
- [ ] `vault.py` decision: copy from siblings OR extract to `auto-review-core`?
      Document in DESIGN.md. (Do NOT block promotion on core extraction.)
- [ ] Tests cover `section_info()` edge cases:
      close-marker found / open heading missing; "0 captures" note; `None` section;
      weekly target-date boundary (the known TODO at `auto-review-doctor:147`)
- [ ] Weekly section detection: verify `section_info()` weekly target-date logic
      against real 2026-05-24 output before cutting v1
- [ ] `deploy/run-auto-review-doctor.sh`: update `auto-review-doctor` invocation
      to use the uv-installed path; re-test on openclaw before swapping
- [ ] Smoke test on openclaw: `uv tool install --reinstall /tmp/auto_review_doctor-*.whl`
      then `auto-review-doctor --dry-run` produces correct output
- [ ] Cron line unchanged (no edit needed): `1 22 * * * run-auto-review-doctor`
- [ ] Retire `doctor/auto-review-doctor` (single-file) after v1 cron is confirmed healthy
- [ ] Update `doctor/README.md` to reflect v1 layout; remove v0 single-file deploy instructions

---

## Part D — What to do next (branching)

After completing Parts A and B, pick exactly one branch:

### Branch 1 — Close cf8, no promotion yet (more data or iteration needed)

**Condition**: Q4 flagged unresolved iteration items, OR weekly row (2026-05-24)
did not render correctly, OR traceback noise is still unresolved by day 7.

```bash
bd close auto-review-cf8 \
  --reason="v0 useful but not promotion-ready: <Q4 finding>. See V0_REVIEW_PREP_2026-05-25.md."
# Then file a new iterate-v0 task under auto-review-3cf:
bd new --title="iterate on auto-review-doctor v0: <finding>" \
       --parent=auto-review-3cf
```

Set a re-review date 1–2 weeks out. Do not run the v1 promotion checklist.

---

### Branch 2 — Close cf8, file v1 promotion task

**Condition**: Q1–Q4 all positive, Part B confirms traceback signal was
visible (or you have a concrete v1 fix for the 815/cgd gap), weekly row
on 2026-05-24 rendered correctly.

```bash
bd close auto-review-cf8 \
  --reason="v0 proved useful across 7 runs; promoting to v1. See V0_REVIEW_PREP_2026-05-25.md."
# File the promotion task:
bd new --title="auto-review-doctor v1 promotion" \
       --parent=auto-review-3cf \
       --notes="Checklist in doctor/V0_REVIEW_PREP_2026-05-25.md Part C."
# If Q3 triggered auto-review-core extraction, file separately:
bd new --title="auto-review-core: extract shared vault.py" \
       --parent=auto-review-3cf
```

---

### Branch 3 — Close cf8, rework v0 (utility failure)

**Condition**: Q1 is "no" — sections were never read, or were actively
confusing. Do not promote until a second review window confirms utility.

```bash
bd close auto-review-cf8 \
  --reason="v0 shape not useful: <specific complaint>. Rework before promotion."
bd new --title="rework auto-review-doctor v0: <complaint>" \
       --parent=auto-review-3cf \
       --notes="Q1/Q4 findings from V0_REVIEW_PREP_2026-05-25.md."
```

After rework, re-run the doctor for ≥1 week and open a new review task.

---

_Prep doc generated 2026-05-25. All local actions target openclaw's vault and
cron.log. Do not SSH, fetch from forgejo, or guess at vault content from here._
