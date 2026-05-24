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
export VAULT_PATH=$HOME/vault
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

First live vault write requires user confirmation. After that, idempotent
reruns are allowed by project policy:

```bash
ssh -o BatchMode=yes <cron-host> 'run-agent-review-daily'
```

## cron entry

Add to the cron-host user crontab only after the smoke test and first live
write are accepted:

```cron
1 21 * * *  run-agent-review-daily  >> $HOME/.local/state/auto-review/cron.log 2>&1
```

This fires at 21:01 daily, 30 minutes after `run-memex-review-daily` and
one hour after `run-recap-daily`, so the jobs do not race on the vault git
lock. Project policy requires user confirmation before editing the cron
host's crontab.

## upgrade

After code changes:

```bash
cd ~/dev/projects/auto-review/agent-review
uv build
scp -o BatchMode=yes dist/agent_review-*.whl <cron-host>:/tmp/
ssh -o BatchMode=yes <cron-host> 'uv tool install --reinstall /tmp/agent_review-*.whl'
```
