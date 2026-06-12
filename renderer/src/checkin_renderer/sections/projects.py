"""projects section: named extension point for auto-review-8cw.

Renders nothing until 8cw's queries/views exist (DESIGN.md, out of scope).
The name is reserved in compose.SECTION_ORDER so the slot in the reading
order is already decided.
"""

from __future__ import annotations

import datetime as dt


def render_projects_section(date: dt.date) -> None:
    """No project views yet; renders nothing."""
    return None


__all__ = ["render_projects_section"]
