"""Core sync behavior against the fake feed + fake DB layer (see conftest)."""

from __future__ import annotations

import pytest

from memex_sync.sync import run_sync, status_snapshot

from .conftest import FakeStore, make_fetch, make_thought


def test_bootstrap_backfills_from_seq_zero(settings, store: FakeStore) -> None:
    """No sync_state row → full-history backfill (since=0), watermark = batch max."""
    rows = [make_thought(i) for i in (1, 2, 3)]
    result = run_sync(settings, connect=store.connect, fetch=make_fetch(rows))

    assert result.bootstrapped
    assert result.since == 0
    assert result.fetched == result.upserted == 3
    assert result.triage_seeded == 3
    assert len(store.captures) == 3
    assert all(t["state"] == "untriaged" for t in store.triage.values())
    assert store.sync_state["memex_sync"] == 3
    assert result.watermark_after == 3


def test_watermark_advance_fetches_only_new(settings, store: FakeStore) -> None:
    store.sync_state["memex_sync"] = 5
    seen: list[int] = []
    inner = make_fetch([make_thought(i) for i in range(1, 9)])

    def fetch(last_seq, *, settings=None):
        seen.append(last_seq)
        return inner(last_seq, settings=settings)

    result = run_sync(settings, connect=store.connect, fetch=fetch)

    assert seen == [5]  # walked from the stored watermark
    assert result.fetched == 3  # seq 6, 7, 8
    assert sorted(p["seq"] for p in store.captures.values()) == [6, 7, 8]
    assert store.sync_state["memex_sync"] == 8
    assert result.watermark_before == 5
    assert result.watermark_after == 8


def test_idle_run_still_records_job_run(settings, store: FakeStore) -> None:
    """Nothing new: no capture/watermark writes, but liveness evidence lands."""
    store.sync_state["memex_sync"] = 8
    result = run_sync(settings, connect=store.connect, fetch=make_fetch([]))

    assert result.fetched == 0
    assert store.captures == {}
    assert store.sync_state == {"memex_sync": 8}  # untouched
    assert len(store.job_runs) == 1
    run = store.job_runs[0]
    assert run["status"] == "ok"
    assert run["job_name"] == "memex-sync"
    assert run["host"] == "testhost"
    assert run["summary"]["fetched"] == 0


def test_redelivery_upsert_is_idempotent(settings, store: FakeStore) -> None:
    """Watermark reset re-delivers rows; dedupe is by capture id (ON CONFLICT)."""
    rows = [make_thought(i) for i in (1, 2)]
    run_sync(settings, connect=store.connect, fetch=make_fetch(rows))
    assert len(store.captures) == 2

    # Re-deliver everything (plus an upstream edit to seq 1's content).
    edited = [make_thought(1, content="edited"), make_thought(2), make_thought(3)]
    result = run_sync(settings, since=0, connect=store.connect, fetch=make_fetch(edited))

    assert result.fetched == 3
    assert len(store.captures) == 3  # no duplicates
    assert store.captures[make_thought(1).id]["content"] == "edited"  # mirror refreshed
    assert store.sync_state["memex_sync"] == 3


def test_triage_seed_never_overwrites_existing_state(settings, store: FakeStore) -> None:
    rows = [make_thought(i) for i in (1, 2)]
    run_sync(settings, connect=store.connect, fetch=make_fetch(rows))

    # The triage surface files capture 1; a watermark-reset re-delivery follows.
    store.triage[make_thought(1).id]["state"] = "filed"
    result = run_sync(settings, since=0, connect=store.connect, fetch=make_fetch(rows))

    assert store.triage[make_thought(1).id]["state"] == "filed"  # preserved
    assert store.triage[make_thought(2).id]["state"] == "untriaged"
    assert result.triage_seeded == 0  # ON CONFLICT DO NOTHING inserted nothing


def test_since_override_persists_watermark_even_when_idle(settings, store: FakeStore) -> None:
    """`--since <head>` on a fresh consumer = explicit bootstrap-at-head."""
    result = run_sync(settings, since=42, connect=store.connect, fetch=make_fetch([]))

    assert result.fetched == 0
    assert store.sync_state["memex_sync"] == 42
    assert result.watermark_after == 42
    assert store.job_runs[0]["summary"]["watermark_after"] == 42


def test_since_override_never_regresses_watermark(settings, store: FakeStore) -> None:
    store.sync_state["memex_sync"] = 50
    result = run_sync(settings, since=10, connect=store.connect, fetch=make_fetch([]))
    assert store.sync_state["memex_sync"] == 50  # max() keeps the high mark
    assert result.watermark_after == 50


def test_error_path_records_error_job_run_and_reraises(settings, store: FakeStore) -> None:
    def fetch(last_seq, *, settings=None):
        raise RuntimeError("feed exploded")

    with pytest.raises(RuntimeError, match="feed exploded"):
        run_sync(settings, connect=store.connect, fetch=fetch)

    assert store.captures == {}
    assert store.sync_state == {}  # main txn rolled back / never wrote
    assert len(store.job_runs) == 1  # recorded on its own connection
    run = store.job_runs[0]
    assert run["status"] == "error"
    assert "feed exploded" in run["summary"]["error"]


def test_failure_mid_run_rolls_back_row_writes(
    settings, store: FakeStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failure after the upserts loses the batch AND the watermark together."""
    import memex_sync.sync as sync_mod

    def boom(conn, consumer, last_seq):
        raise RuntimeError("watermark write failed")

    monkeypatch.setattr(sync_mod, "set_watermark", boom)

    with pytest.raises(RuntimeError, match="watermark write failed"):
        run_sync(settings, connect=store.connect, fetch=make_fetch([make_thought(1)]))

    assert store.captures == {}  # upserts rolled back with the txn
    assert "memex_sync" not in store.sync_state
    assert store.job_runs[0]["status"] == "error"  # recorded on its own connection


def test_dry_run_writes_nothing_not_even_job_runs(settings, store: FakeStore) -> None:
    rows = [make_thought(i) for i in (1, 2)]
    result = run_sync(settings, dry_run=True, connect=store.connect, fetch=make_fetch(rows))

    assert result.dry_run
    assert result.fetched == 2
    assert [t.seq for t in result.thoughts] == [1, 2]
    assert store.captures == {}
    assert store.sync_state == {}
    assert store.job_runs == []


def test_status_snapshot(settings, store: FakeStore) -> None:
    rows = [make_thought(i) for i in (1, 2, 3)]
    run_sync(settings, connect=store.connect, fetch=make_fetch(rows))
    store.triage[make_thought(2).id]["state"] = "filed"

    snap = status_snapshot(settings, connect=store.connect, head_fn=lambda *, settings: 5)

    assert snap.consumer == "memex_sync"
    assert snap.watermark == 3
    assert snap.server_head == 5
    assert snap.captures == 3
    assert snap.untriaged == 2
