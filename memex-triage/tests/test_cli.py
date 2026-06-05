"""End-to-end CLI tests: bootstrap, sync delivery, status."""

from __future__ import annotations

import httpx
import pytest
import respx
from click.testing import CliRunner

import memex_triage.config as config
from memex_triage import inbox
from memex_triage.cli import main

THOUGHTS_URL = "https://memex.example/api/thoughts"


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch, tmp_path):
    monkeypatch.setenv("MEMEX_URL", "https://memex.example/api")
    monkeypatch.setenv("MEMEX_CLIENT_ID", "id")
    monkeypatch.setenv("MEMEX_CLIENT_SECRET", "secret")
    monkeypatch.setenv("VAULT_PATH", str(tmp_path))
    monkeypatch.setenv("TZ", "UTC")
    monkeypatch.setenv("INBOX_PATH", "inbox/memex.md")
    monkeypatch.setattr(config, "_settings", None)  # reset cached singleton
    return tmp_path


def _row(seq: int) -> dict:
    ts = 1_700_000_000_000 + seq * 60_000
    return {
        "id": f"{seq:08d}-1111-2222-3333-444444444444",
        "seq": seq,
        "content_preview": f"content {seq}",
        "source": "test",
        "summary": None,
        "tags": [],
        "created_at": ts,
        "updated_at": ts,
    }


def _mock_corpus(rows: list[dict]):
    """Respond to both the recency head probe (?limit=1) and the feed (?since=)."""

    def responder(request: httpx.Request) -> httpx.Response:
        params = request.url.params
        if "since" in params:
            since = int(params["since"])
            limit = int(params["limit"])
            return httpx.Response(200, json=[r for r in rows if r["seq"] > since][:limit])
        # recency default: newest (max seq) first
        ordered = sorted(rows, key=lambda r: r["seq"], reverse=True)
        return httpx.Response(200, json=ordered[: int(params.get("limit", 10))])

    respx.get(THOUGHTS_URL).mock(side_effect=responder)


@respx.mock
def test_sync_bootstraps_at_head_then_delivers(env) -> None:
    _mock_corpus([_row(i) for i in range(1, 62)])  # seq 1..61
    runner = CliRunner()

    # First sync: bootstrap at head, deliver nothing.
    r1 = runner.invoke(main, ["sync"])
    assert r1.exit_code == 0, r1.output
    assert "bootstrapped" in r1.output
    s = config.get_settings()
    assert inbox.load_last_seq(s) == 61
    assert inbox.count_task_lines(s) == 0

    # A new capture arrives (seq 62); next sync delivers it.
    _mock_corpus([_row(i) for i in range(1, 63)])
    r2 = runner.invoke(main, ["sync"])
    assert r2.exit_code == 0, r2.output
    assert inbox.load_last_seq(s) == 62
    assert inbox.count_task_lines(s) == 1


@respx.mock
def test_sync_dry_run_does_not_write(env) -> None:
    _mock_corpus([_row(i) for i in range(1, 4)])
    s = config.get_settings()
    inbox.init_inbox(0, settings=s)  # watermark at 0 → 3 pending
    runner = CliRunner()

    r = runner.invoke(main, ["sync", "--dry-run", "--print"])
    assert r.exit_code == 0, r.output
    assert "would append 3" in r.output
    assert "^mx-00000001" in r.output  # --print emitted the lines
    assert inbox.load_last_seq(s) == 0  # unchanged
    assert inbox.count_task_lines(s) == 0


@respx.mock
def test_sync_idempotent_when_up_to_date(env) -> None:
    _mock_corpus([_row(i) for i in range(1, 4)])
    s = config.get_settings()
    inbox.init_inbox(3, settings=s)
    runner = CliRunner()
    r = runner.invoke(main, ["sync"])
    assert r.exit_code == 0, r.output
    assert "nothing new" in r.output
    assert inbox.count_task_lines(s) == 0


@respx.mock
def test_init_backfill_then_status(env) -> None:
    _mock_corpus([_row(i) for i in range(1, 11)])  # seq 1..10
    runner = CliRunner()

    ri = runner.invoke(main, ["init", "--backfill", "0"])
    assert ri.exit_code == 0, ri.output

    rs = runner.invoke(main, ["status"])
    assert rs.exit_code == 0, rs.output
    assert "server head: seq 10" in rs.output
    assert "watermark:  seq 0" in rs.output
    assert "pending:    10" in rs.output


@respx.mock
def test_init_refuses_existing(env) -> None:
    _mock_corpus([_row(1)])
    s = config.get_settings()
    inbox.init_inbox(0, settings=s)
    runner = CliRunner()
    r = runner.invoke(main, ["init"])
    assert r.exit_code == 2
    assert "refusing to clobber" in r.output
