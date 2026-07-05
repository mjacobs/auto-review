# deploy/

agent-review is designed to run on a Linux host (`<cron-host>`) under
cron, using the same wheel + `uv tool` + wrapper pattern as the other
auto-review siblings.

## one-time install

From your dev box, build a wheel and copy it to the cron host:

```bash
cd ~/dev/projects/auto-review/agent-review
uv build
scp -o BatchMode=yes dist/agent_review-*.whl <cron-host>:/tmp/
scp -o BatchMode=yes deploy/run-agent-review-daily.sh <cron-host>:/tmp/
```

On the cron host, install the tool and wrapper:

```bash
ssh -o BatchMode=yes <cron-host> 'uv tool install --reinstall /tmp/agent_review-*.whl && \
  mv -f /tmp/run-agent-review-daily.sh ~/.local/bin/run-agent-review-daily && \
  chmod +x ~/.local/bin/run-agent-review-daily'
```

Project policy requires user confirmation before running the install/wrapper
drop above.

## secrets

The wrapper sources `~/.secrets` and requires:

```bash
export PG_DSN='...'
export LLM_API_KEY='...'
```

Optional exports:

```bash
export TZ=America/Los_Angeles
export MODEL_DIGEST=claude-haiku-4-5-20251001
export MODEL_SYNTH=claude-sonnet-4-6
export PGPASSFILE=$HOME/.pgpass
```

If `PG_DSN` omits the password, provision `~/.pgpass` on the cron host with
mode `600`. Do not print secret values to stdout while provisioning.
Project policy requires user confirmation before writing to the cron
host's `~/.secrets`.

Verify presence by count only:

```bash
ssh -o BatchMode=yes <cron-host> 'grep -c "^export PG_DSN=" ~/.secrets; grep -c "^export LLM_API_KEY=" ~/.secrets'
```

## smoke tests

Non-writing DB/config smoke test:

```bash
ssh -o BatchMode=yes <cron-host> 'source ~/.secrets && agent-review extract yesterday --print >/tmp/agent-review-extract.json'
```

The wrapper runs `agent-review run yesterday` (ADR 002 / `auto-review-hg6.6`):
agent-review is DB-only, so it persists the daily report to the `agent_review`
PG schema and touches **no files** — there is no vault write and no git path
here (the check-in renderer emits the section from PG). Idempotent reruns upsert
the same row:

```bash
ssh -o BatchMode=yes <cron-host> 'run-agent-review-daily'
```

## cron entry

Add to the cron-host user crontab only after the smoke test and first live
write are accepted:

```cron
21 0 * * *  run-agent-review-daily  >> $HOME/.local/state/auto-review/cron.log 2>&1
```

This fires at 00:21 daily, 20 minutes after `run-recap-daily` (vault-review),
and clears the `agentsview pg push` at 00:00 so the day's sessions are present.
It writes only its PG row (no git path), and the check-in renderer at 00:51
reads that row to emit the section. The chain runs just after midnight so each
day's report materializes right after the day closes. Project policy requires
user confirmation before editing the cron host's crontab.

## upgrade

After code changes:

```bash
cd ~/dev/projects/auto-review/agent-review
uv build
scp -o BatchMode=yes dist/agent_review-*.whl <cron-host>:/tmp/
ssh -o BatchMode=yes <cron-host> 'uv tool install --reinstall /tmp/agent_review-*.whl'
```
