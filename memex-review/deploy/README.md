# deploy/

Installation pattern lifted from vault-review/deploy. memex-review is
designed to run on a Linux host (`<cron-host>`) under cron.

## one-time install

From your dev box, build a wheel and copy to the cron host:

```bash
cd ~/dev/projects/auto-review/memex-review
uv build                                 # produces dist/memex_review-*.whl
scp dist/memex_review-*.whl <cron-host>:/tmp/
scp deploy/run-memex-review-daily.sh <cron-host>:~/.local/bin/
```

On the cron host:

```bash
ssh <cron-host>

# install the tool (uv must be on PATH)
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

Add to the cron host's user crontab (`crontab -e`):

```
31 20 * * *  run-memex-review-daily  >> $HOME/.local/state/auto-review/cron.log 2>&1
```

This fires at 20:31 daily — 30 minutes after `run-recap-daily` (vault-review)
so the two don't race on the vault repo's git lock.

All three siblings (`agent-review`, `vault-review`, `memex-review`) write
into the **day they review** (i.e., yesterday's check-in note), not the
day they run.

## upgrade

After code changes:

```bash
cd ~/dev/projects/auto-review/memex-review
uv build
scp dist/memex_review-*.whl <cron-host>:/tmp/
ssh <cron-host> 'uv tool install --reinstall /tmp/memex_review-*.whl'
```

## cron log

Shares `~/.local/state/auto-review/cron.log` with the other auto-review
siblings. Per-tool log split is parked future work.
