# deploy/

Installation pattern lifted from the sibling tools. memex-sync runs on a
Linux host (`<cron-host>`) under cron, against the shared Postgres instance
(`<pg-host>`). It writes **only** database rows — no vault checkout, no git.

## prerequisites (one-time, admin)

1. **Schema applied.** `db/migrations/` (0001 ops, 0002 memex, 0005 roles)
   must be live — see `db/README.md` "The apply gate".

2. **Role password.** The `memex_sync` role is created by `0005_roles.sql`
   with no password. Set one out-of-band:

   ```bash
   export PG_DSN='postgresql://<admin>@<pg-host>:5432/<db>'
   export PGPASS_MEMEX_SYNC='...'   # from your secrets store
   ~/dev/projects/auto-review/db/set-role-passwords.sh
   ```

3. **Job registered.** `ops.job_runs.job_name` has an FK to `ops.jobs`, and
   the `memex_sync` role deliberately cannot insert registry rows — register
   the job once as admin (this is also what makes the doctor monitor it):

   ```sql
   INSERT INTO ops.jobs (name, host, cadence, writes, monitored, expected_interval)
   VALUES ('memex-sync', '<cron-host>', 'hourly',
           'memex.captures mirror + triage seeds + sync watermark',
           true, interval '2 hours')
   ON CONFLICT (name) DO NOTHING;
   ```

   (Adjust `cadence`/`expected_interval` to match the cron line you pick;
   keep the doctor's `JOBS` registry in step per AGENTS.md.)

## one-time install

From your dev box, build a wheel and copy to the cron host:

```bash
cd ~/dev/projects/auto-review/memex-sync
uv build                                 # produces dist/memex_sync-*.whl
scp dist/memex_sync-*.whl <cron-host>:/tmp/
scp deploy/run-memex-sync.sh <cron-host>:~/.local/bin/run-memex-sync
```

On the cron host:

```bash
ssh <cron-host>

# install the tool (uv must be on PATH)
uv tool install /tmp/memex_sync-*.whl
chmod +x ~/.local/bin/run-memex-sync

# provision creds if not already present. ~/.secrets must export:
#   PG_DSN (postgresql://memex_sync@<pg-host>:5432/<db>),
#   MEMEX_URL, MEMEX_CLIENT_ID, MEMEX_CLIENT_SECRET
# (copy from the dev box via the ssh-stdin pipe in AGENTS.md "Secrets policy";
#  the role password can instead live in ~/.pgpass: <pg-host>:5432:<db>:memex_sync:...)
vim ~/.secrets

# smoke test, read-only:
source ~/.secrets && memex-sync status
memex-sync sync --dry-run --print | head -20

# first real run: backfills the FULL capture history from seq 0 (intended —
# the canonical store wants everything). To skip history instead:
#   memex-sync sync --since "$(memex-sync status | awk '/server head/ {print $4}')"
run-memex-sync
```

## cron entry

Add to the cron host's user crontab (`crontab -e`):

```
41 * * * *  run-memex-sync  >> $HOME/.local/state/auto-review/cron.log 2>&1
```

Hourly at :41 keeps it well clear of the just-after-midnight daily chain
(:01/:11/:21) — the siblings race on the vault git lock, which memex-sync
doesn't touch, but the stagger keeps the shared log readable. An idle hour
still inserts one `ops.job_runs` row (~liveness heartbeat); the row volume
(24/day) is noise-level.

Match `expected_interval` in `ops.jobs` to whatever cadence you choose
(rule of thumb: 2x the cron interval).

## upgrade

```bash
cd ~/dev/projects/auto-review/memex-sync
uv build
scp dist/memex_sync-*.whl <cron-host>:/tmp/
ssh <cron-host> 'uv tool install --reinstall /tmp/memex_sync-*.whl'
```

## cron log

Shares `~/.local/state/auto-review/cron.log` with the other auto-review
siblings. Per-tool log split is parked future work.
