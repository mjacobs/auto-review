"""vault-review section: vault_review.daily_digests.events -> dossier.

Phase 3 / step C (DESIGN.md decision 3, auto-review-hg6.7): once the producer
writes rows, the renderer owns this section. A pure-function port of
vault-review's dossier.render_events — it formats the stored `events` jsonb
(status/path/group/summary, per-file summaries captured at digest time) instead
of calling summarize_file, so it needs no vault access. A missing row renders a
`_no vault digest row_` placeholder (the producer hasn't landed one yet).

Repo convention is independent siblings (no shared library), so the
grouping/formatting is a small verbatim port of render_events; the round-trip
equivalence is guarded in vault-review's test_dossier.
"""

from __future__ import annotations

import datetime as dt

from ..queries import VaultDigestRow


def render_vault_section(digest: VaultDigestRow | None, date: dt.date) -> str:
    """Render the vault-review dossier section body (no trailing newline)."""
    heading = f"## vault-review — {date.isoformat()}"
    if digest is None:
        return f"{heading}\n\n_no vault digest row for {date.isoformat()}_"

    by_group: dict[str, list[str]] = {}
    for e in digest.events:
        status = e["status"]
        path = e["path"]
        if status == "A":
            line = f"- `+` `{path}` — {e['summary']}"
        elif status == "M":
            line = f"- `~` `{path}` — {e['summary']}"
        elif status == "D":
            line = f"- `-` `{path}`"
        elif status.startswith("R"):
            line = f"- `↻` `{path}` (renamed from `{e['renamed_from']}`)"
        else:
            line = f"- `?` {status} `{path}`"
        by_group.setdefault(e["group"], []).append(line)

    out = [heading, "", f"_window: {date.isoformat()}_", ""]
    if not by_group:
        out.append("_no authored changes in window_")
        return "\n".join(out)
    for g in sorted(by_group):
        out.append(f"### {g}")
        out.extend(by_group[g])
        out.append("")
    return "\n".join(out).rstrip("\n")


__all__ = ["render_vault_section"]
