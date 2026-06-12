# checkin-renderer

One writer for the daily check-in note: reads the per-domain Postgres schemas
(`ops`, `memex`, `vault_review`, `projects`, `agent_review`) and emits
`journal/checkins/YYYY/MM/YYYY-MM-DD.md` as a generated view of the database —
regenerable at any time, byte-identical for the same rows. Replaces the
marker-bracket sibling writers section by section (memex + agent first, then
vault-review, then the doctor's health section and the whole-file flip).

See [`DESIGN.md`](./DESIGN.md) for the architecture (ADR 002), the transition
sequencing, and the phase plan; [`deploy/README.md`](./deploy/README.md) for
cron-host installation.

```
checkin-renderer run [DATE|RANGE]        # default: yesterday (cron target)
checkin-renderer run --dry-run --print   # render to stdout, no write, no run-row
checkin-renderer show DATE               # print current bracket (or note) for DATE
checkin-renderer sections DATE           # per-section row availability (debug)
```

Config (env / `.env`): `CHECKIN_RENDERER_PG_DSN` (required; password may come
from `~/.pgpass`), `VAULT_PATH`, `TZ`, `RENDER_MODE` (`bracket`|`full` —
`full` is the gated step-D flip).

Development:

```bash
cd renderer
uv run pytest
uv run ruff check .
```
