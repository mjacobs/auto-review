"""CLI tests: verb wiring + output, with sync/status seams faked via the store."""

from __future__ import annotations

import pytest
import respx
from click.testing import CliRunner

import memex_sync.cli as cli_mod
import memex_sync.config as config
from memex_sync.cli import main, render_line

from .conftest import FakeStore, make_fetch, make_thought


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PG_DSN", "postgresql://memex_sync@db.example:5432/agentsview")
    monkeypatch.setenv("MEMEX_URL", "https://memex.example/api")
    monkeypatch.setenv("MEMEX_CLIENT_ID", "id")
    monkeypatch.setenv("MEMEX_CLIENT_SECRET", "secret")
    monkeypatch.setenv("MEMEX_SYNC_HOST", "testhost")
    monkeypatch.setattr(config, "_settings", None)  # reset cached singleton


@pytest.fixture
def store(env, monkeypatch: pytest.MonkeyPatch) -> FakeStore:
    """Route the CLI's run_sync/status_snapshot through the fake store."""
    import memex_sync.sync as sync_mod

    fake = FakeStore()
    fake.feed = []  # the fake change-feed corpus

    real_run_sync = sync_mod.run_sync
    real_status = sync_mod.status_snapshot

    def run_sync(settings, **kwargs):
        kwargs.setdefault("connect", fake.connect)
        kwargs.setdefault("fetch", make_fetch(fake.feed))
        return real_run_sync(settings, **kwargs)

    def status_snapshot(settings, **kwargs):
        kwargs.setdefault("connect", fake.connect)
        kwargs.setdefault("head_fn", lambda *, settings: max((t.seq for t in fake.feed), default=0))
        return real_status(settings, **kwargs)

    monkeypatch.setattr(cli_mod, "run_sync", run_sync)
    monkeypatch.setattr(cli_mod, "status_snapshot", status_snapshot)
    return fake


def test_sync_bootstrap_backfills_and_reports(store: FakeStore) -> None:
    store.feed = [make_thought(i) for i in (1, 2)]
    r = CliRunner().invoke(main, ["sync"])
    assert r.exit_code == 0, r.output
    assert "bootstrap" in r.output
    assert "upserted 2 capture(s)" in r.output
    assert store.sync_state["memex_sync"] == 2
    assert len(store.job_runs) == 1


def test_bare_invocation_defaults_to_sync(store: FakeStore) -> None:
    store.feed = [make_thought(1)]
    r = CliRunner().invoke(main, [])
    assert r.exit_code == 0, r.output
    assert store.sync_state["memex_sync"] == 1


def test_sync_dry_run_print_writes_nothing(store: FakeStore) -> None:
    store.feed = [make_thought(i) for i in (1, 2, 3)]
    r = CliRunner().invoke(main, ["sync", "--dry-run", "--print"])
    assert r.exit_code == 0, r.output
    assert "--dry-run" in r.output
    assert r.output.count("seq ") >= 3  # --print emitted the rows
    assert store.captures == {}
    assert store.sync_state == {}
    assert store.job_runs == []


def test_sync_since_override(store: FakeStore) -> None:
    store.feed = [make_thought(i) for i in (1, 2, 3)]
    store.sync_state["memex_sync"] = 3
    r = CliRunner().invoke(main, ["sync", "--since", "1"])
    assert r.exit_code == 0, r.output
    assert sorted(p["seq"] for p in store.captures.values()) == [2, 3]
    assert store.sync_state["memex_sync"] == 3


def test_status_reports_watermark_and_counts(store: FakeStore) -> None:
    store.feed = [make_thought(i) for i in (1, 2, 3)]
    CliRunner().invoke(main, ["sync"])

    r = CliRunner().invoke(main, ["status"])
    assert r.exit_code == 0, r.output
    assert "server head: seq 3" in r.output
    assert "watermark:   seq 3" in r.output
    assert "captures:    3 row(s)" in r.output
    assert "untriaged:   3 row(s)" in r.output


def test_status_unset_watermark(store: FakeStore) -> None:
    r = CliRunner().invoke(main, ["status"])
    assert r.exit_code == 0, r.output
    assert "backfills the full history from seq 0" in r.output


def test_sync_error_exits_nonzero(store: FakeStore, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(settings, **kwargs):
        raise RuntimeError("db unreachable")

    monkeypatch.setattr(cli_mod, "run_sync", boom)
    r = CliRunner().invoke(main, ["sync"])
    assert r.exit_code != 0


def test_render_line_shape() -> None:
    t = make_thought(7)
    line = render_line(t)
    assert line.startswith("seq 7  ")
    assert t.id in line
    assert "content 7" in line
    assert "#alpha" in line


@pytest.fixture(autouse=True)
def _no_network() -> None:
    """CLI tests stub the head probe; nothing should hit the network."""
    with respx.mock:
        yield
