"""weekly section: vault_review.weekly_digests -> weekly dossier appendix.

Phase 3 / step C (DESIGN.md decision 6): `run-weekly` strip-and-replaces a
permanent `checkin-renderer:begin/end weekly=YYYY-W##` bracket — the machine
appendix inside a human document — once hg6.7's producer writes
weekly_digests rows. Nothing to render until then; the CLI verb exists as a
flagged stub.
"""

from __future__ import annotations

__all__: list[str] = []
