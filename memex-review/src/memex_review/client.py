"""cf-memex /thoughts API client.

Pure data-fetch layer: paginate `GET /thoughts?limit=100&before=<ms>` backwards
from the end of a window, accumulating thoughts whose `created_at` falls in
`[start, end)`. No vault writes here.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Iterable

import httpx

from .config import Settings, get_settings

PAGE_SIZE = 100


@dataclass(frozen=True)
class Thought:
    id: str
    content_preview: str
    source: str | None
    summary: str | None
    tags: tuple[str, ...]
    created_at_ms: int
    updated_at_ms: int

    @property
    def created_at(self) -> dt.datetime:
        return dt.datetime.fromtimestamp(self.created_at_ms / 1000, tz=dt.timezone.utc)


def _to_thought(row: dict) -> Thought:
    tags = row.get("tags") or []
    if isinstance(tags, str):
        import json

        try:
            tags = json.loads(tags)
        except (ValueError, TypeError):
            tags = []
    return Thought(
        id=row["id"],
        content_preview=row.get("content_preview") or row.get("content") or "",
        source=row.get("source"),
        summary=row.get("summary"),
        tags=tuple(tags),
        created_at_ms=int(row["created_at"]),
        updated_at_ms=int(row["updated_at"]),
    )


def _headers(settings: Settings) -> dict[str, str]:
    return {
        "CF-Access-Client-Id": settings.memex_client_id.get_secret_value(),
        "CF-Access-Client-Secret": settings.memex_client_secret.get_secret_value(),
        "Accept": "application/json",
    }


def _ms(dt_: dt.datetime) -> int:
    if dt_.tzinfo is None:
        raise ValueError("naive datetime; supply tzinfo")
    return int(dt_.timestamp() * 1000)


def collect_thoughts(
    start: dt.datetime,
    end: dt.datetime,
    *,
    settings: Settings | None = None,
    client: httpx.Client | None = None,
) -> list[Thought]:
    """Return thoughts with `start <= created_at < end`, oldest first.

    Paginates from `before=end_ms` backwards, stopping when a page's tail
    falls below `start_ms`. The Worker enforces a max page size of 100.
    """
    if end <= start:
        return []
    settings = settings or get_settings()
    base = settings.memex_url.rstrip("/")
    start_ms, end_ms = _ms(start), _ms(end)

    owned_client = client is None
    client = client or httpx.Client(timeout=30.0)
    try:
        collected: list[Thought] = []
        before = end_ms
        seen_ids: set[str] = set()
        while True:
            resp = client.get(
                f"{base}/thoughts",
                params={"limit": PAGE_SIZE, "before": before},
                headers=_headers(settings),
            )
            resp.raise_for_status()
            rows = resp.json()
            if not rows:
                break
            page_min_ms = rows[-1]["created_at"]
            for row in rows:
                ts = int(row["created_at"])
                if start_ms <= ts < end_ms and row["id"] not in seen_ids:
                    collected.append(_to_thought(row))
                    seen_ids.add(row["id"])
            if page_min_ms < start_ms or len(rows) < PAGE_SIZE:
                break
            before = page_min_ms
        collected.sort(key=lambda t: t.created_at_ms)
        return collected
    finally:
        if owned_client:
            client.close()


def collect_for_date(
    date: dt.date,
    *,
    settings: Settings | None = None,
    client: httpx.Client | None = None,
) -> list[Thought]:
    """Thoughts whose local-time creation date is `date`."""
    settings = settings or get_settings()
    tz = settings.tz
    start = dt.datetime.combine(date, dt.time.min, tzinfo=tz)
    end = start + dt.timedelta(days=1)
    return collect_thoughts(start, end, settings=settings, client=client)


__all__ = ["Thought", "collect_thoughts", "collect_for_date", "PAGE_SIZE"]


def _iter_pages_for_debug(  # pragma: no cover - manual smoke tool
    settings: Settings | None = None,
) -> Iterable[list[dict]]:
    """Generator that yields raw /thoughts pages newest-to-oldest (debug aid)."""
    settings = settings or get_settings()
    base = settings.memex_url.rstrip("/")
    with httpx.Client(timeout=30.0) as client:
        before: int | None = None
        while True:
            params = {"limit": PAGE_SIZE}
            if before is not None:
                params["before"] = before
            resp = client.get(f"{base}/thoughts", params=params, headers=_headers(settings))
            resp.raise_for_status()
            rows = resp.json()
            if not rows:
                return
            yield rows
            if len(rows) < PAGE_SIZE:
                return
            before = rows[-1]["created_at"]
