# memex-triage — deploy

Unlike the other auto-review siblings (daily cron on the LXC runner),
`memex-triage` runs on the **Fedora desktop** as a `systemd --user` timer every
5 minutes. The desktop is where you triage `inbox/memex.md`, so making it the
sole writer of that note and its watermark avoids any two-writer race.

## What gets installed

| Artifact | Destination | Role |
|---|---|---|
| `memex-triage` (uv tool) | `~/.local/bin/memex-triage` | the CLI |
| `run-memex-triage.sh` | `~/.local/bin/run-memex-triage` | sync + commit/push the inbox |
| `memex-triage.service` | `~/.config/systemd/user/` | oneshot that runs the wrapper |
| `memex-triage.timer` | `~/.config/systemd/user/` | `*/5`, `Persistent=true` |

Credentials (`MEMEX_URL`, `MEMEX_CLIENT_ID`, `MEMEX_CLIENT_SECRET`) come from
`~/.secrets`, sourced by the wrapper. `VAULT_PATH`/`INBOX_PATH`/`TZ` may also be
set there (defaults: `~/vault`, `inbox/memex.md`, `America/Los_Angeles`).

## Install

```bash
cd ~/dev/projects/auto-review/memex-triage

# 1. Install the CLI
uv tool install --reinstall .

# 2. Install the wrapper
install -m755 deploy/run-memex-triage.sh ~/.local/bin/run-memex-triage

# 3. Install the systemd --user units
mkdir -p ~/.config/systemd/user
cp deploy/memex-triage.service deploy/memex-triage.timer ~/.config/systemd/user/
systemctl --user daemon-reload
```

## First run — bootstrap by hand, then enable the timer

The very first `sync` performs the **first live write to `~/vault/inbox/memex.md`**
and bootstraps the watermark at the current server head (delivering nothing).
Do it manually so you can eyeball it before automating:

```bash
source ~/.secrets
memex-triage status          # sanity: server head, inbox path, watermark unset
memex-triage sync            # creates inbox/memex.md at head; no captures yet
git -C "$HOME/vault" status  # confirm only inbox/memex.md is new/changed
```

To instead pull recent history into the inbox on day one:

```bash
memex-triage init --backfill <seq>   # e.g. a seq a few below head; see `status`
```

Then turn on the timer:

```bash
systemctl --user enable --now memex-triage.timer
systemctl --user list-timers memex-triage.timer   # confirm next run
```

> [!NOTE]
> For the timer to keep firing while you're logged out (and to fully honor
> `Persistent=true` across reboots), enable lingering once:
> `loginctl enable-linger "$USER"`. If you only want it running during an
> active desktop session, skip this.

## Verify / observe

```bash
systemctl --user start memex-triage.service     # run once now
journalctl --user -u memex-triage.service -n 30 # logs (stdout/stderr → journal)
systemctl --user list-timers memex-triage.timer
```

## Update

```bash
cd ~/dev/projects/auto-review/memex-triage
uv tool install --reinstall .
install -m755 deploy/run-memex-triage.sh ~/.local/bin/run-memex-triage
# if a unit changed:
cp deploy/memex-triage.{service,timer} ~/.config/systemd/user/ && systemctl --user daemon-reload
```

## Uninstall

```bash
systemctl --user disable --now memex-triage.timer
rm ~/.config/systemd/user/memex-triage.{service,timer}
systemctl --user daemon-reload
rm -f ~/.local/bin/run-memex-triage
uv tool uninstall memex-triage
# inbox/memex.md is yours — left in place.
```

## Notes

- **Single writer.** Only this desktop writes `inbox/memex.md` + its `last_seq`
  frontmatter. Don't also run the timer on another host against the same vault.
- **Commit scope.** The wrapper commits *only* `inbox/memex.md` (not `git add
  -A`) and uses `git pull --rebase --autostash`, so a `*/5` run never sweeps up
  your in-progress edits to other notes and never bails on a dirty tree.
- **Idle is free.** Polls with no new captures do nothing — no write, no commit.
