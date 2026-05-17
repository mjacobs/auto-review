# deploy/

Installation pattern lifted from vault-review/deploy. memex-review runs on
openclaw (OPENCLAW_HOST, user `openclaw`) under cron.

## one-time install

From the dev box, build a wheel and copy to openclaw:

```bash
cd ~/dev/projects/auto-review/memex-review
uv build                                 # produces dist/memex_review-*.whl
scp dist/memex_review-*.whl openclaw@OPENCLAW_HOST:/tmp/
scp deploy/run-memex-review-daily.sh openclaw@OPENCLAW_HOST:~/.local/bin/
```

On openclaw:

```bash
ssh openclaw@OPENCLAW_HOST

# install the tool (Linuxbrew uv must be on PATH)
uv tool install /tmp/memex_review-*.whl

# make the wrapper executable
chmod +x ~/.local/bin/run-memex-review-daily

# provision CF Access creds if not already present
#   ~/.secrets must export MEMEX_URL, MEMEX_CLIENT_ID, MEMEX_CLIENT_SECRET
vim ~/.secrets

# smoke test (won't write because vault git push would fail without creds, but
# you'll see the section render)
run-memex-review-daily 2>&1 | head -30
```

## cron entry

Add to the openclaw user crontab (`crontab -e`):

```
31 20 * * *  run-memex-review-daily  >> /home/openclaw/.local/state/vault-agent/cron.log 2>&1
```

This fires at 20:31 daily — 30 minutes after `run-recap-daily` (vault-review)
so the two don't race on the vault repo's git lock.

Per project doc, all three siblings (`agent-review`, `vault-review`,
`memex-review`) write into the **day they review** (i.e., yesterday's
check-in note), not the day they run.

## upgrade

After code changes:

```bash
cd ~/dev/projects/auto-review/memex-review
uv build
scp dist/memex_review-*.whl openclaw@OPENCLAW_HOST:/tmp/
ssh openclaw@OPENCLAW_HOST 'uv tool install --reinstall /tmp/memex_review-*.whl'
```

## cron log

Shares `~/.local/state/vault-agent/cron.log` with the other auto-review
siblings. See `auto-review-{TBD}` / project doc for the planned per-tool
log split.
