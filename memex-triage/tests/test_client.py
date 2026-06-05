"""Tests for the cf-memex change-feed client."""

from __future__ import annotations

import httpx
import pytest
import respx

from memex_triage.client import PAGE_SIZE, fetch_since, server_head
from memex_triage.config import Settings

THOUGHTS_URL = "https://memex.example/api/thoughts"


@pytest.fixture
def settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.setenv("MEMEX_URL", "https://memex.example/api")
    monkeypatch.setenv("MEMEX_CLIENT_ID", "id")
    monkeypatch.setenv("MEMEX_CLIENT_SECRET", "secret")
    return Settings()


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
def test_server_head_returns_newest_seq(settings: Settings) -> None:
    respx.get(THOUGHTS_URL).mock(return_value=httpx.Response(200, json=[_row(61)]))
    assert server_head(settings=settings) == 61


@respx.mock
def test_server_head_empty_corpus(settings: Settings) -> None:
    respx.get(THOUGHTS_URL).mock(return_value=httpx.Response(200, json=[]))
    assert server_head(settings=settings) == 0
