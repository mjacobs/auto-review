# vault-review — design

## Goals

Generate a deterministic, audit-friendly dossier of what changed in the
Obsidian vault on a given day or ISO week, and write it idempotently into
the vault itself. No LLM, no Postgres, no side effects — just `git log` →
markdown → file write.

The tool is a sibling of `agent-review`, which does the same shape of work
over Claude Code session transcripts. Both follow the same CLI idioms
(`run today`, `run-weekly last-week`, `--dry-run`, `--print`), the same
pydantic-settings config shape, and the same marker-based idempotency story,
so the two tools behave like interchangeable peers.

## Marker-based idempotency

Each write appends a section bounded by a predictable HTML comment marker:

```
## vault-review — 2026-05-14

_window: 2026-05-14_

### journal
- `~` `journal/checkins/2026-05-14.md` — …

<!-- vault-review:daily=2026-05-14 generated_at=2026-05-15T04:00:00Z -->
```

The section regex matches from `## vault-review` through the closing marker
(`re.DOTALL`). On every run, `write_daily_section` / `write_weekly_section`:

1. Loads frontmatter with `python-frontmatter` (preserves YAML header intact).
2. Strips any existing marked section via the regex.
3. Appends the new section.
4. Writes back.

Human edits _outside_ the marked section survive. The file is safe to edit by
hand between runs.

## What `collect_events` gives you

`gitdelta.collect_events(vault_path, start, end)` runs:

```
git log --since=<start_iso> --until=<end_iso> \
        --no-merges --diff-filter=AMDR -M \
        --name-status --pretty=format:
```

The `-M` flag collapses rename pairs into single `R…` events. The denylist
drops `.obsidian/`, `.git/`, `archive/`, `templates/`, `x-attach/`, and
`gemini-scribe/` paths — structural or machine-generated noise. Only `.md`
files pass through; config files and attachments are not signal.

`start` and `end` are explicit `datetime` objects (not relative strings like
`"24 hours ago"`), which makes the window reproducible: the same
`run yesterday` call at 4 AM and at 11 PM produces the same set of commits.

## File structure

```
src/vault_review/
  config.py     pydantic-settings; VAULT_PATH, TZ
  gitdelta.py   collect_events() — git log → [(status, path1, path2)]
  dossier.py    render_dossier(), summarize_file(), group_of()
  weekly.py     parse_week(), week_date_range(), day_date_range()
  vault.py      write/read/remove for daily and weekly sections
  cli.py        click CLI: run, today, yesterday, run-weekly, show, reset, …
```

## What's intentionally out of scope (v1)

**No Telegram, no git commit/push.** The cron wrapper keeps owning
those side effects. A small shell wrapper (in `deploy/`) calls `vault-review`
and then does the `git add/commit/push` afterward.

**No LLM.** The recap is deterministic per ADR 006. `anthropic` is not a
dependency.

**No Postgres.** Sections live in the vault files. If a `show`-from-DB
query, a web viewer, or per-week cost tracking is needed later, a
`vault_review` schema mirroring `agent_review.daily_reports` is a natural
extension — the section marker format was designed to make that migration
mechanical.

## Deferred: serverless-memex-review

A third sibling tool — `memex-review` — would do the same shape of work
(`run today`, `run-weekly`) over the Cloudflare memex store instead of git.
Same CLI surface, same marker idempotency, same pydantic-settings config.
The intent is that all three tools (`agent-review`, `vault-review`,
`memex-review`) share muscle memory and can be composed in the same cron
wrapper pattern.
