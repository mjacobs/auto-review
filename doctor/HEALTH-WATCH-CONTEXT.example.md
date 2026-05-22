# auto-review health-watch — playbook (example skeleton)

This is a template. The real playbook is operator-specific (your hosts,
your IPs, your incident history) and should not live in this public
repo. Copy this file to a private location and point the watch at it:

```bash
# Recommended deployed location:
mkdir -p ~/.config/auto-review
cp doctor/HEALTH-WATCH-CONTEXT.example.md \
   ~/.config/auto-review/HEALTH-WATCH-CONTEXT.md
# Then edit it with your real landmines.
```

The `health-watch` script resolves the playbook in this order:

1. `--context PATH` flag.
2. `HEALTH_WATCH_CONTEXT` env var.
3. `~/.config/auto-review/HEALTH-WATCH-CONTEXT.md` (recommended).
4. `~/.local/share/auto-review/HEALTH-WATCH-CONTEXT.md` (legacy deployed path).
5. This example file, as a sibling of the script (with a warning).

The watch reads the resolved file verbatim each morning. Make it
specific: the more concretely a landmine is described, the more the LLM
can verify against it instead of hallucinating "looks fine."

---

## Structure expected by the watch

The watch's prompt template references the sections below by name and
expects each landmine to be addressed in the output. Keep these
headings and the `L1 / L2 / ...` landmine pattern; rewrite the contents
for your deployment.

---

## Pipeline shape

Describe the cron schedule and the symptom-of-success line each job
writes to the log. Example:

| time  | job                       | symptom of success in cron.log |
|------:|---------------------------|-------------------------------|
| 20:01 | `run-recap-daily`         | `vault-review: daily recap <iso-utc>` commit line |
| 20:31 | `run-memex-review-daily`  | `memex-review: daily inbox <iso-utc>` commit line |
| 21:01 | `run-agent-review-daily`  | `agent-review: daily report <iso-utc>` commit line |
| 22:01 | `run-auto-review-doctor`  | `auto-review doctor: daily health <iso-utc>` commit line |

List external dependencies the pipeline relies on: the LLM gateway,
the source databases, the vault remote, etc. Use placeholder names —
do not commit real internal IPs or hostnames to a public repo.

---

## Watch principles

Keep these verbatim; the watch reads them as instructions.

- Default to suspicion. Anything other than fully-green gets a full
  investigation paragraph, not a one-line "looks fine."
- Quote evidence from the inputs (cron.log lines, sibling sections,
  timestamps). Never restate the prompt as a finding.
- Re-discovery of a known landmine is wasted effort. For each entry
  below, look first for the symptom string and confirm the fix is
  still in place before concluding green.
- Verdict is binary: GREEN or NON-GREEN. There is no yellow. If
  unsure, it is NON-GREEN.

---

## Known landmines

Add one entry per recurring failure mode you have actually seen. The
shape below is what the prompt expects; the contents are illustrative
only.

### L1 — example: API-key rotation

**Symptom**: `anthropic.AuthenticationError: 401 invalid x-api-key`
in cron.log, attached to any sibling traceback. Root cause is usually
a rotated upstream key, or a token-type confusion (OAuth token used
where an API key is required).

**Check each run**: any new `AuthenticationError` or
`401 invalid x-api-key` in the 24h window → investigate which key
the wrapper is loading. NON-GREEN.

### L2 — example: gateway / upstream unreachable

**Symptom**: `ConnectionRefusedError` or HTTP 5xx from your LLM
gateway. Often happens after the gateway host reboots and the
service does not auto-start.

**Check each run**: any `Connection refused`, `Could not connect to
server`, or 5xx from the gateway address in cron.log → NON-GREEN.
Also flag if a sibling section is *missing* from yesterday's check-in
without another obvious cause — absence is the symptom.

### L3 — example: cost runaway

Set a steady-state cost expectation per sibling that does LLM work.
Example thresholds:

- Single day > 8× steady-state: anomalous, investigate.
- Sustained > 3× across 2+ consecutive days: investigate.
- Trend up by >2× day-over-day: investigate.

**Check each run**: parse the cost line from the relevant sibling's
section. NON-GREEN at threshold breach.

### L4 — example: vault push failure

The vault auto-syncs; each sibling wrapper does its own `git push`
after committing. If a push fails, the section is created on the
cron host but never reaches the workstation.

**Check each run**: scan cron.log for `! [rejected]`, `failed to
push`, or non-zero exit messages near a sibling's commit line.
NON-GREEN if any are found in the 24h window.

---

## What "GREEN" requires

All of these must be true:

1. All expected sibling commits present in cron.log for the
   24h window ending at the watch's run time.
2. All expected sibling sections present in yesterday's check-in
   note, with markers intact and non-trivial body content.
3. No new tracebacks in cron.log within the 24h window.
4. No new symptoms matching any landmine above.
5. LLM cost within the expected band.

If any one fails, NON-GREEN with evidence-backed findings.
