"""vault-review section: vault_review.daily_digests.events -> dossier.

Phase 3 / step C (DESIGN.md decision 3): vault_review.daily_digests is empty
until hg6.7 teaches the producer to write rows, so vault-review keeps writing
its own marker section and this module renders nothing. When rows exist, this
becomes a pure-function port of vault-review's dossier.render_dossier
grouping/formatting reading the `events` jsonb instead of calling
summarize_file; a missing row renders a `_no digest row for D_` placeholder.
"""

from __future__ import annotations

import datetime as dt


def render_vault_section(date: dt.date) -> None:
    """Not rendered before step C; vault-review still owns its marker section."""
    return None


__all__ = ["render_vault_section"]
