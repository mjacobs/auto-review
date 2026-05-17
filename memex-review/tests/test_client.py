"""Tests for the /thoughts API client."""

from __future__ import annotations

import datetime as dt

import httpx
import pytest
import respx

from memex_review.client import PAGE_SIZE, Thought, collect_thoughts
from memex_review.config import Settings


@pytest.fixture
def settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.setenv("MEMEX_URL", "https://memex.example/api")
    monkeypatch.setenv("MEMEX_CLIENT_ID", "id")
    monkeypatch.setenv("MEMEX_CLIENT_SECRET", "secret")
    return Settings()


def _row(ts_ms: int, *, id_: str | None = None, tags: list[str] | None = None) -> dict:
    return {
        "id": id_ or f"id-{ts_ms}",
        "content_preview": f"content at {ts_ms}",
        "source": "test",
        "summary": None,
        "tags": tags or [],
        "created_at": ts_ms,
        "updated_at": ts_ms,
    }


def _window(start_iso: str, end_iso: str) -> tuple[dt.datetime, dt.datetime]:
    return (
        dt.datetime.fromisoformat(start_iso).replace(tzinfo=dt.timezone.utc),
        dt.datetime.fromisoformat(end_iso).replace(tzinfo=dt.timezone.utc),
    )


@respx.mock
def test_collect_thoughts_filters_window(settings: Settings) -> None:
    start, end = _window("2026-05-15T00:00:00", "2026-05-16T00:00:00")
    start_ms = int(start.timestamp() * 1000)
    end_ms = int(end.timestamp() * 1000)

    in_window = [_row(start_ms + 60_000), _row(start_ms + 3_600_000)]
    before_window = [_row(start_ms - 60_000)]
    rows = sorted(in_window + before_window, key=lambda r: r["created_at"], reverse=True)

    respx.get("https://memex.example/api/thoughts").mock(
        return_value=httpx.Response(200, json=rows)
    )

    out = collect_thoughts(start, end, settings=settings)

    assert [t.created_at_ms for t in out] == sorted(r["created_at"] for r in in_window)
    assert all(start_ms <= t.created_at_ms < end_ms for t in out)


@respx.mock
def test_collect_thoughts_paginates_until_under_start(settings: Settings) -> None:
    start, end = _window("2026-05-15T00:00:00", "2026-05-16T00:00:00")
    start_ms = int(start.timestamp() * 1000)
    end_ms = int(end.timestamp() * 1000)

    # Page 1: a full page entirely inside the window.
    page1 = [_row(end_ms - 1000 - i * 1000, id_=f"a{i}") for i in range(PAGE_SIZE)]
    # Page 2: tail dips below start_ms, signalling stop.
    page2 = [_row(start_ms + 5000, id_="b0"), _row(start_ms - 1000, id_="b1")]

    route = respx.get("https://memex.example/api/thoughts").mock(
        side_effect=[httpx.Response(200, json=page1), httpx.Response(200, json=page2)]
    )

    out = collect_thoughts(start, end, settings=settings)

    assert route.call_count == 2
    # Page 2's before= must equal page 1's oldest created_at.
    second_call_params = dict(httpx.QueryParams(route.calls[1].request.url.query.decode()))
    assert int(second_call_params["before"]) == page1[-1]["created_at"]
    # All page-1 rows are in window; only b0 from page-2 is in window.
    assert {t.id for t in out} == {f"a{i}" for i in range(PAGE_SIZE)} | {"b0"}


@respx.mock
def test_collect_thoughts_sends_cf_access_headers(settings: Settings) -> None:
    start, end = _window("2026-05-15T00:00:00", "2026-05-16T00:00:00")
    route = respx.get("https://memex.example/api/thoughts").mock(
        return_value=httpx.Response(200, json=[])
    )
    collect_thoughts(start, end, settings=settings)
    req = route.calls[0].request
    assert req.headers["CF-Access-Client-Id"] == "id"
    assert req.headers["CF-Access-Client-Secret"] == "secret"


@respx.mock
def test_collect_thoughts_returns_oldest_first(settings: Settings) -> None:
    start, end = _window("2026-05-15T00:00:00", "2026-05-16T00:00:00")
    start_ms = int(start.timestamp() * 1000)
    rows = [_row(start_ms + 1000 * k, id_=f"i{k}") for k in (5, 1, 3, 2, 4)]
    respx.get("https://memex.example/api/thoughts").mock(
        return_value=httpx.Response(200, json=rows)
    )
    out = collect_thoughts(start, end, settings=settings)
    assert [t.id for t in out] == ["i1", "i2", "i3", "i4", "i5"]


@respx.mock
def test_collect_thoughts_empty_response(settings: Settings) -> None:
    start, end = _window("2026-05-15T00:00:00", "2026-05-16T00:00:00")
    respx.get("https://memex.example/api/thoughts").mock(
        return_value=httpx.Response(200, json=[])
    )
    assert collect_thoughts(start, end, settings=settings) == []


def test_thought_created_at_property() -> None:
    t = Thought(
        id="x",
        content_preview="c",
        source=None,
        summary=None,
        tags=(),
        created_at_ms=1_715_000_000_000,
        updated_at_ms=1_715_000_000_000,
    )
    assert t.created_at.tzinfo is not None
    assert t.created_at == dt.datetime.fromtimestamp(1_715_000_000, tz=dt.timezone.utc)
