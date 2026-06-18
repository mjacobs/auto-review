# memex-triage-cli

Terminal-native triage of memex captures held in Postgres — the replacement for
checking boxes in `inbox/memex.md` (`auto-review-hg6.9`). It reads the captures
mirror (`memex.captures`) and flips PG-owned triage state
(`memex.capture_triage`) — and **nothing else**. It never touches the D1 change
feed and never writes the captures mirror; the `memex_triage` role's grants
(SELECT on both tables, `UPDATE(state, updated_at)` on `capture_triage`, no
INSERT/DELETE — [`../db/migrations/0005_roles.sql`](../db/migrations/0005_roles.sql))
enforce that boundary.

A sibling of `agent-review` / `vault-review` / `memex-sync` / `memex-triage`.
The companion writer is `memex-sync`, which mirrors captures from
[serverless-memex](https://github.com/mjacobs/serverless-memex) into the `memex`
schema and seeds one `'untriaged'` triage row per capture. This CLI only ever
*flips* an existing triage row — by construction the row already exists, so the
tool never INSERTs one.

## CLI

```
memex-triage-cli                       # = memex-triage-cli list
memex-triage-cli list                  # untriaged captures, numbered, seq-ordered
memex-triage-cli list --state filed    # or: untriaged | discarded
memex-triage-cli file 12 14            # mark seqs 12 and 14 filed
memex-triage-cli discard 13            # mark seq 13 discarded
memex-triage-cli reset 12              # return seq 12 to untriaged
memex-triage-cli file deadbeef         # an id-prefix also resolves
```

Each row of `list` is one scannable line: `seq  HH:MM  id-prefix  summary
(or first content line)  #tag …`. Mutating verbs accept the human-visible
`seq` shown there (or an id-prefix), resolve it to the capture id, run the flip
in a single transaction, and echo `<seq> -> <state>`. An unknown or ambiguous
identifier aborts the whole batch (nothing is written) and exits non-zero.

## Config

Via env / `.env` (pydantic-settings; see [`.env.example`](./.env.example)):

| var | required | meaning |
|---|---|---|
| `MEMEX_TRIAGE_PG_DSN` | yes | DSN for the `memex_triage` role; password optional if `~/.pgpass` (or a repo-local `.pgpass`) has an entry |
| `TZ` | no | display timezone for the listing's `HH:MM` column (default `America/Los_Angeles`) |

## Development

```bash
cd memex-triage-cli
uv sync
uv run pytest
uv run ruff check src tests
```

Tests run against an in-memory fake of the PG layer — no live database or
network. The fake dispatches on the module-level SQL constants in `queries.py`
and, mirroring the role grants, refuses to invent a triage row on UPDATE.
