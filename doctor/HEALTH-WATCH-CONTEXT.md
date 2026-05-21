# auto-review health-watch — known-landmines playbook

Bundled context for the daily health-watch. Extend this file (in the repo)
as new failure modes are observed. The watch reads it verbatim each
morning and is instructed to verify each landmine has not recurred.

**Watch principles** (these are not optional):

- Default to suspicion. Anything other than fully-green gets a full
  investigation paragraph, not a one-line "looks fine."
- Quote evidence from the inputs (cron.log lines, sibling sections,
  timestamps). Never restate the prompt as a finding.
- Re-discovery of a known landmine is wasted effort. For each entry
  below, look first for the symptom string and confirm the fix is still
  in place before concluding green.
- Verdict is binary: GREEN or NON-GREEN. There is no yellow. If unsure,
  it is NON-GREEN.

---

## Pipeline shape (as of 2026-05-21)

Four daily jobs on openclaw cron (all times PT):

| time  | job                       | symptom of success in cron.log |
|------:|---------------------------|-------------------------------|
| 20:01 | `run-recap-daily`         | `vault-review: daily recap <iso-utc>` commit line |
| 20:31 | `run-memex-review-daily`  | `memex-review: daily inbox <iso-utc>` commit line |
| 21:01 | `run-agent-review-daily`  | `agent-review: daily report <iso-utc>` commit line |
| 22:01 | `run-auto-review-doctor`  | `auto-review doctor: daily health <iso-utc>` commit line |

Each writes a marker-bracketed section into today's check-in note at
`~/vault/journal/checkins/YYYY-MM-DD.md`. The doctor reports on
*yesterday's* check-in. Sundays add a weekly `vault-review` fire at 10:01.

External dependencies:

- LiteLLM gateway at `http://PORTAINER_HOST:4000` (portainer VM, VLAN 5).
- agentsview Postgres at `POSTGRES_HOST:5432` (VLAN 5).
- Anthropic API (reached *through* LiteLLM as of 2026-05-21).
- Forgejo vault remote (the vault auto-syncs every 5 min).

---

## Known landmines

### L1 — OAuth-vs-API-key token-type bug (resolved 2026-05-21)

**Symptom**: `anthropic.AuthenticationError: 401 invalid x-api-key` in
cron.log, attached to `agent-review` traceback. Root cause was setting
`ANTHROPIC_API_KEY=$MAIN_ANTHROPIC_TOKEN`, where `MAIN_ANTHROPIC_TOKEN`
is an `sk-ant-oat01-…` OAuth token (Claude Code), not an `sk-ant-api03-…`
API key. The Messages API rejects OAuth tokens with a 401.

**Fix in place**: `ANTHROPIC_API_KEY` on openclaw is now
`$LITELLM_KEY_AGENT_REVIEW` (an `sk-…` LiteLLM virtual key, not an
Anthropic key), and `ANTHROPIC_BASE_URL=http://PORTAINER_HOST:4000`
routes through the homelab gateway.

**Check each run**: any new `AuthenticationError` or `401 invalid x-api-key`
in cron.log → investigate which key the wrapper is loading and confirm
it is not an OAuth token. NON-GREEN.

### L2 — portainer/LiteLLM autostart gap (open: `auto-review-zvv`)

**Symptom**: gateway requests fail with `ConnectionRefusedError` or
HTTP 502/503 from `PORTAINER_HOST:4000`. Observed 2026-05-21 after the
portainer VM rebooted from a system update — the LiteLLM compose stack
did not auto-start.

**Fix not yet in place** — tracked separately. Until then, the watch
must surface this aggressively because it silently breaks agent-review
for the night.

**Check each run**: any `Connection refused`, `Could not connect to
server`, or 5xx mentioning `PORTAINER_HOST` in cron.log → NON-GREEN. Also
flag if the agent-review section is missing from yesterday's check-in
without an obvious other cause (the absence is the symptom).

### L3 — doctor traceback-count tail lag

The doctor's `_N tracebacks in log tail_` count is over the last 1000
lines of cron.log, not over a date window. After the 2026-05-21 fix
landed, this count should drain *day over day* as clean lines push the
old `agent-review` 401-error tracebacks out of the tail.

**Expected drain trajectory** (from baseline 34 on 2026-05-21):

- 2026-05-22: expect significant drop (one clean night replaces ~30+ old failure lines)
- 2026-05-24 onwards: expect single-digit or zero

**Check each run**: if the doctor's traceback count is *not strictly
lower* than the prior day (modulo new tracebacks from today's run), new
failures are arriving — that is the actual signal, the old residue is
draining. Quote the trend explicitly. If a new traceback appeared that
is not L1/L2 in origin, that's a new landmine to add to this file.

### L4 — vault-review recursion fix (resolved 2026-05-21)

Before the fix, vault-review's daily section listed every file in
`journal/checkins/` and `journal/weekly/` that changed in the window —
which meant it recursively reported the *sibling tools'* writes as
"vault activity." On quiet authoring days the section was 100%
recursive noise.

**Fix in place**: `journal/checkins/` and `journal/weekly/` added to
the gitdelta denylist. Confirmed in
`vault-review/src/vault_review/gitdelta.py`.

**Check each run**: read yesterday's vault-review section. If any
bullet references `journal/checkins/YYYY-MM-DD.md` or
`journal/weekly/…`, the deployed openclaw install is still the
pre-fix version. Reinstall instruction in the finding:

```
ssh openclaw@OPENCLAW_HOST \
  uv tool install --reinstall \
  "git+https://github.com/mjacobs/auto-review.git#subdirectory=vault-review"
```

NON-GREEN if the recursive bullets are present.

### L5 — agent-review code-version skew (latent)

agent-review on openclaw was reinstalled 2026-05-21 from
`git+https://github.com/mjacobs/auto-review.git#subdirectory=agent-review`.
Any future change to agent-review (e.g. prompt tweaks, schema changes,
new tool support) requires explicit re-install — there is no auto-update.

**Check each run**: confirm the agent-review section shape conforms to
the documented template (heading `## agent-review — YYYY-MM-DD …`,
cost line, narrative paragraph(s), `### by project`, `### artifacts`,
`### stuck / open`, `### stats` table, close marker). If the shape has
silently regressed but the code on GitHub still has the original shape,
suspect a stale install.

### L6 — cost runaway

Steady-state digest+synth cost is ~$0.06/day (per `DESIGN.md`).
Observed real-day range 2026-05-19 → 2026-05-20: $0.07 to $0.16.

**Thresholds**:

- Single day > $0.50: anomalous, investigate (runaway session, very
  long transcripts, prompt cache disabled, model misconfigured).
- Sustained > $0.20/day across 2+ consecutive days: investigate.
- Trend up by >2× day-over-day: investigate.

**Check each run**: parse the `est. cost` cell from the agent-review
stats table. NON-GREEN at threshold breach.

### L7 — memex captures consistently zero

As of 2026-05-21 the user is not yet routinely capturing thoughts to
`serverless-memex`. The memex-review section reading `0 captures` is
**expected** and is GREEN. This is a user-discipline question, not a
tool bug.

**Check each run**: if memex-review section is *missing*, NON-GREEN
(that's a tool failure). If captures > 0 but the section is empty,
malformed, or has no listing under any tag, NON-GREEN (that's a
hydration bug). 0 captures with a present, well-formed section is
GREEN.

### L8 — vault git push failures

The vault auto-syncs via `vault-sync-pull` every 5 min, and each
sibling wrapper does its own `git push` after committing. If a push
fails (rejected for non-fast-forward, network blip, forgejo down), the
section gets created on openclaw but never propagates to the user's
workstation.

**Check each run**: scan cron.log for `! [rejected]`, `failed to push`,
or non-zero exit messages near a sibling's commit line. NON-GREEN
if any are found in the 24h window.

### L9 — Postgres reachability for agent-review

agent-review reads `agentsview.*` as the `agent_review` PG user
(provisioned 2026-05-21, read-only on agentsview / CRUD on the cache
schema). If `POSTGRES_HOST:5432` is unreachable or the user's grants are
revoked, agent-review fails with `psycopg.OperationalError` or
`InsufficientPrivilege`.

**Check each run**: any `psycopg` or `OperationalError` near
agent-review lines → NON-GREEN. Specifically watch for
`permission denied for schema` which would indicate the `pine`-owned
default-privileges grant was reset (e.g. by a schema redeploy).

---

## What "GREEN" requires

All of these must be true:

1. All four expected sibling commits present in cron.log for the
   24h window ending at the watch's run time.
2. All four sibling sections present in yesterday's check-in note,
   with markers intact and non-trivial body content.
3. No tracebacks in cron.log within the 24h window (older tracebacks
   draining from L3 are fine — quote the drain trend).
4. No new symptoms matching L1, L2, L4, L8, L9.
5. agent-review cost within the L6 band.
6. agent-review section shape conforms (L5).

If any one fails, NON-GREEN with evidence-backed findings.
