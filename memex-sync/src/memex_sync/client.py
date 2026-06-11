"""cf-memex change-feed client.

Pure data-fetch layer over `GET /thoughts?since=<seq>` — the monotonic seq
change feed added in serverless-memex (migration 0003). Walking the feed from a
single high-water mark gives gap-free, exactly-once delivery independent of
created_at. No DB writes here.

Adapted from memex-triage/src/memex_triage/client.py (repo convention is
independent siblings, no shared library). One naming difference: the field is
called `content` here because that is what memex.captures stores — but the
feed serves `content_preview` (capped), falling back to `content` when the
worker provides it. See README "preview limitation".
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass

import httpx

from .config import Settings, get_settings

PAGE_SIZE = 100


@dataclass(frozen=True)
class Thought:
    id: str
    seq: int
    content: str
    source: str | None
    summary: str | None
    tags: tuple[str, ...]
    created_at_ms: int
    updated_at_ms: int

    @property
    def created_at(self) -> dt.datetime:
        return dt.datetime.fromtimestamp(self.created_at_ms / 1000, tz=dt.UTC)

    @property
    def updated_at(self) -> dt.datetime:
        return dt.datetime.fromtimestamp(self.updated_at_ms / 1000, tz=dt.UTC)


def _to_thought(row: dict) -> Thought:
    tags = row.get("tags") or []
    if isinstance(tags, str):
        try:
            tags = json.loads(tags)
        except (ValueError, TypeError):
            tags = []
    return Thought(
        id=row["id"],
        seq=int(row["seq"]),
        content=row.get("content_preview") or row.get("content") or "",
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


def fetch_since(
    last_seq: int,
    *,
    settings: Settings | None = None,
    client: httpx.Client | None = None,
) -> list[Thought]:
    """Return all captures with `seq > last_seq`, ascending by seq.

    Pages `GET /thoughts?since=<cursor>` forward (the Worker caps pages at 100),
    advancing the cursor to each page's max seq, until a short page.
    """
    settings = settings or get_settings()
    base = settings.memex_url.rstrip("/")

    owned_client = client is None
    client = client or httpx.Client(timeout=30.0)
    try:
        collected: list[Thought] = []
        cursor = last_seq
        while True:
            resp = client.get(
                f"{base}/thoughts",
                params={"limit": PAGE_SIZE, "since": cursor},
                headers=_headers(settings),
            )
            resp.raise_for_status()
            rows = resp.json()
            if not rows:
                break
            collected.extend(_to_thought(r) for r in rows)
            cursor = max(int(r["seq"]) for r in rows)
            if len(rows) < PAGE_SIZE:
                break
        collected.sort(key=lambda t: t.seq)
        return collected
    finally:
        if owned_client:
            client.close()


def server_head(
    *,
    settings: Settings | None = None,
    client: httpx.Client | None = None,
) -> int:
    """The current max seq on the server (0 if the corpus is empty).

    Uses the recency default (`?limit=1`), whose newest-by-created_at row is the
    most recently inserted and therefore carries the max seq. Used by `status`
    to show how far the mirror lags. Under-estimating here is safe; nothing
    advances the watermark from this value.
    """
    settings = settings or get_settings()
    base = settings.memex_url.rstrip("/")
    owned_client = client is None
    client = client or httpx.Client(timeout=30.0)
    try:
        resp = client.get(
            f"{base}/thoughts",
            params={"limit": 1},
            headers=_headers(settings),
        )
        resp.raise_for_status()
        rows = resp.json()
        return int(rows[0]["seq"]) if rows else 0
    finally:
        if owned_client:
            client.close()


__all__ = ["Thought", "fetch_since", "server_head", "PAGE_SIZE"]
