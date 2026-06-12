"""monthly section: calendar-month fold over daily-grain rows (auto-review-2l1).

Phase 4 (DESIGN.md decision 6): `run-monthly YYYY-MM` writes
journal/monthly/YYYY-MM.md (skeleton + bracket) from vault_review.daily_digests
rollups, agent_review.daily_reports.stats sums, and memex.captures counts —
never touching weeklies, avoiding the ISO-week/partial-month mismatch.
Nothing to render in Phase 1; the CLI verb exists as a flagged stub.
"""

from __future__ import annotations

__all__: list[str] = []
