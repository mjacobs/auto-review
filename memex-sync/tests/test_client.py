"""Tests for the cf-memex change-feed client (adapted from memex-triage)."""

from __future__ import annotations

import httpx
import pytest
import respx

from memex_sync.client import PAGE_SIZE, fetch_since, server_head
from memex_sync.config import Settings

THOUGHTS_URL = "https://memex.example/api/thoughts"


def _row(seq: int) -> dict:
    ts = 1_700_000_000_000 + seq
    return {
        "id": f"id-{seq:04d}-aaaa-bbbb",
        "seq": seq,
        "content_preview": f"content {seq}",
        "source": "test",
        "summary": None,
        "tags": [],
        "created_at": ts,
        "updated_at": ts,
    }


@respx.mock
def test_fetch_since_paginates_ascending(settings: Settings) -> None:
    rows = [_row(i) for i in range(1, 2 * PAGE_SIZE + 51)]  # 250 rows

    def responder(request: httpx.Request) -> httpx.Response:
        since = int(request.url.params["since"])
        limit = int(request.url.params["limit"])
        page = [r for r in rows if r["seq"] > since][:limit]
        return httpx.Response(200, json=page)

    respx.get(THOUGHTS_URL).mock(side_effect=responder)

    out = fetch_since(0, settings=settings)
    assert [t.seq for t in out] == list(range(1, 2 * PAGE_SIZE + 51))


@respx.mock
def test_fetch_since_respects_watermark(settings: Settings) -> None:
    rows = [_row(i) for i in range(1, 11)]

    def responder(request: httpx.Request) -> httpx.Response:
        since = int(request.url.params["since"])
        return httpx.Response(200, json=[r for r in rows if r["seq"] > since])

    respx.get(THOUGHTS_URL).mock(side_effect=responder)

    out = fetch_since(7, settings=settings)
    assert [t.seq for t in out] == [8, 9, 10]


@respx.mock
def test_fetch_since_empty_feed(settings: Settings) -> None:
    respx.get(THOUGHTS_URL).mock(return_value=httpx.Response(200, json=[]))
    assert fetch_since(99, settings=settings) == []


@respx.mock
def test_fetch_since_sends_access_headers(settings: Settings) -> None:
    route = respx.get(THOUGHTS_URL).mock(return_value=httpx.Response(200, json=[]))
    fetch_since(0, settings=settings)
    req = route.calls.last.request
    assert req.headers["CF-Access-Client-Id"] == "id"
    assert req.headers["CF-Access-Client-Secret"] == "secret"


@respx.mock
def test_content_prefers_preview_falls_back_to_full(settings: Settings) -> None:
    rows = [
        {**_row(1), "content_preview": "preview text", "content": "full text"},
        {**_row(2), "content_preview": None, "content": "full only"},
    ]
    respx.get(THOUGHTS_URL).mock(return_value=httpx.Response(200, json=rows))
    out = fetch_since(0, settings=settings)
    assert out[0].content == "preview text"
    assert out[1].content == "full only"


@respx.mock
def test_server_head_returns_newest_seq(settings: Settings) -> None:
    respx.get(THOUGHTS_URL).mock(return_value=httpx.Response(200, json=[_row(61)]))
    assert server_head(settings=settings) == 61


@respx.mock
def test_server_head_empty_corpus(settings: Settings) -> None:
    respx.get(THOUGHTS_URL).mock(return_value=httpx.Response(200, json=[]))
    assert server_head(settings=settings) == 0


def test_timestamps_are_utc(settings: Settings) -> None:
    import datetime as dt

    from .conftest import make_thought

    t = make_thought(1)
    assert t.created_at.tzinfo == dt.UTC
    assert t.updated_at.tzinfo == dt.UTC


@pytest.fixture(autouse=True)
def _no_real_db(monkeypatch: pytest.MonkeyPatch) -> None:
    """Belt-and-braces: client tests must never open a PG connection."""
    import memex_sync.db as db

    def boom() -> None:  # pragma: no cover
        raise AssertionError("client tests must not touch the database")

    monkeypatch.setattr(db, "connect", boom)
