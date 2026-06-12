"""health section: ops.jobs ⨝ latest job_runs -> health table.

Phase 4 / step D (DESIGN.md decision 7): health ships last, when
hg6.6/6.7/6.8 have put rows under every job — until then a PG-rendered health
table would be mostly blank, and the doctor's check-in writer keeps running
unchanged. Full-render mode only.
"""

from __future__ import annotations

import datetime as dt


def render_health_section(date: dt.date) -> None:
    """Not rendered before step D; the doctor still owns the health section."""
    return None


__all__ = ["render_health_section"]
