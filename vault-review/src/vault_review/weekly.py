"""ISO-week math and weekly synthesis rendering."""

from __future__ import annotations

import datetime as dt

from .config import get_settings


def parse_week(s: str, today: dt.date | None = None) -> str:
    """Parse a week spec into a 'YYYY-W##' label.

    Accepts:
      - 'this-week' → current ISO week
      - 'last-week' → previous ISO week
      - 'YYYY-W##'  → validated and returned as-is

    Args:
        s: Week spec string.
        today: Override today's date (defaults to configured TZ's today).

    Returns:
        ISO week label like '2026-W19'.

    Raises:
        ValueError: If the input cannot be parsed.
    """
    if today is None:
        today = dt.datetime.now(get_settings().tz).date()
    s = s.strip().lower()
    if s == "this-week":
        iso_year, iso_week, _ = today.isocalendar()
        return f"{iso_year}-W{iso_week:02d}"
    if s == "last-week":
        prev = today - dt.timedelta(weeks=1)
        iso_year, iso_week, _ = prev.isocalendar()
        return f"{iso_year}-W{iso_week:02d}"
    # Try YYYY-W## (case-insensitive, already lowercased)
    s_upper = s.upper()
    import re
    m = re.fullmatch(r"(\d{4})-W(\d{1,2})", s_upper)
    if m:
        year = int(m.group(1))
        week = int(m.group(2))
        # Validate by round-tripping through fromisocalendar
        try:
            dt.date.fromisocalendar(year, week, 1)
        except ValueError as exc:
            raise ValueError(f"invalid ISO week: {s!r}") from exc
        return f"{year}-W{week:02d}"
    raise ValueError(
        f"cannot parse week spec: {s!r} — "
        "use 'this-week', 'last-week', or 'YYYY-W##'"
    )


def week_date_range(week_label: str) -> tuple[dt.datetime, dt.datetime]:
    """Return (start, end) datetimes for a week label.

    Start = Monday 00:00:00, End = following Monday 00:00:00 (exclusive).
    Both are naive local datetimes suitable for git log --since/--until.
    """
    iso_year, iso_week = int(week_label[:4]), int(week_label[6:])
    monday = dt.date.fromisocalendar(iso_year, iso_week, 1)
    start = dt.datetime.combine(monday, dt.time.min)
    end = dt.datetime.combine(monday + dt.timedelta(weeks=1), dt.time.min)
    return start, end


def day_date_range(date: dt.date) -> tuple[dt.datetime, dt.datetime]:
    """Return (start, end) datetimes for a single calendar day.

    Start = 00:00:00, End = 23:59:59 on the same day (inclusive window).
    Using end-of-day rather than next-day midnight avoids capturing commits
    made after midnight on the next calendar day.
    """
    start = dt.datetime.combine(date, dt.time.min)
    end = dt.datetime.combine(date, dt.time(23, 59, 59))
    return start, end
