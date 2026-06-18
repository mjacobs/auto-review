"""CLI tests: verb wiring + output, with the triage seams faked via the store."""

from __future__ import annotations

import pytest
from click.testing import CliRunner

import memex_triage_cli.cli as cli_mod
import memex_triage_cli.config as config
from memex_triage_cli.cli import main, render_line
from memex_triage_cli.triage import Capture

from .conftest import FakeStore, make_capture


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MEMEX_TRIAGE_PG_DSN", "postgresql://memex_triage@db.example:5432/agentsview")
    monkeypatch.setenv("TZ", "UTC")
    monkeypatch.setattr(config, "_settings", None)  # reset cached singleton


@pytest.fixture
def store(env, monkeypatch: pytest.MonkeyPatch) -> FakeStore:
    """Route the CLI's list_inbox/set_states through the fake store."""
    import memex_triage_cli.triage as triage_mod

    fake = FakeStore()
    real_list = triage_mod.list_inbox
    real_set = triage_mod.set_states

    def list_inbox(state="untriaged", **kwargs):
        kwargs.setdefault("connect", fake.connect)
        return real_list(state, **kwargs)

    def set_states(seqs, state, **kwargs):
        kwargs.setdefault("connect", fake.connect)
        return real_set(seqs, state, **kwargs)

    monkeypatch.setattr(cli_mod, "list_inbox", list_inbox)
    monkeypatch.setattr(cli_mod, "set_states", set_states)
    return fake


def test_list_renders_seq_ordered_untriaged(store: FakeStore) -> None:
    store.seed(make_capture(2, summary="second"), make_capture(1, summary="first"))
    r = CliRunner().invoke(main, ["list"])
    assert r.exit_code == 0, r.output
    lines = [ln for ln in r.output.splitlines() if ln.strip()]
    assert len(lines) == 2
    assert lines[0].split()[0] == "1"  # seq-ordered
    assert lines[1].split()[0] == "2"
    assert "first" in lines[0]
    assert "second" in lines[1]


def test_bare_invocation_defaults_to_list(store: FakeStore) -> None:
    store.seed(make_capture(1, summary="hi"))
    r = CliRunner().invoke(main, [])
    assert r.exit_code == 0, r.output
    assert "hi" in r.output


def test_list_state_filed(store: FakeStore) -> None:
    store.seed(make_capture(1, summary="u"), make_capture(2, state="filed", summary="f"))
    r = CliRunner().invoke(main, ["list", "--state", "filed"])
    assert r.exit_code == 0, r.output
    assert "f" in r.output
    assert "u" not in r.output


def test_list_empty_state_message(store: FakeStore) -> None:
    r = CliRunner().invoke(main, ["list"])
    assert r.exit_code == 0, r.output
    assert "no captures" in r.output


def test_file_verb_flips_and_echoes(store: FakeStore) -> None:
    store.seed(make_capture(12))
    r = CliRunner().invoke(main, ["file", "12"])
    assert r.exit_code == 0, r.output
    assert "12 -> filed" in r.output
    assert store.state_of(12) == "filed"


def test_discard_verb(store: FakeStore) -> None:
    store.seed(make_capture(3))
    r = CliRunner().invoke(main, ["discard", "3"])
    assert r.exit_code == 0, r.output
    assert "3 -> discarded" in r.output
    assert store.state_of(3) == "discarded"


def test_reset_verb(store: FakeStore) -> None:
    store.seed(make_capture(4, state="filed"))
    r = CliRunner().invoke(main, ["reset", "4"])
    assert r.exit_code == 0, r.output
    assert "4 -> untriaged" in r.output
    assert store.state_of(4) == "untriaged"


def test_file_multiple_seqs(store: FakeStore) -> None:
    store.seed(make_capture(1), make_capture(2))
    r = CliRunner().invoke(main, ["file", "1", "2"])
    assert r.exit_code == 0, r.output
    assert "1 -> filed" in r.output
    assert "2 -> filed" in r.output
    assert store.state_of(1) == store.state_of(2) == "filed"


def test_file_by_id_prefix(store: FakeStore) -> None:
    store.seed(make_capture(9, capture_id="deadbeef-0000-0000-0000-000000000000"))
    r = CliRunner().invoke(main, ["file", "deadbeef"])
    assert r.exit_code == 0, r.output
    assert "deadbeef -> filed" in r.output
    assert store.state_of(9) == "filed"


def test_unknown_seq_errors_nonzero_and_writes_nothing(store: FakeStore) -> None:
    store.seed(make_capture(1))
    r = CliRunner().invoke(main, ["file", "999"])
    assert r.exit_code != 0
    assert "no capture matches" in r.output
    assert store.state_of(1) == "untriaged"


def test_mutating_verb_requires_an_argument(store: FakeStore) -> None:
    r = CliRunner().invoke(main, ["file"])
    assert r.exit_code != 0  # nargs=-1 with required=True


def test_render_line_shape() -> None:
    import datetime as dt
    from zoneinfo import ZoneInfo

    cap = Capture(
        id="abcd1234-5678-0000-0000-000000000000",
        seq=7,
        content="body line",
        summary="a summary",
        tags=("Cash Investment", "alpha"),
        created_at=dt.datetime(2026, 6, 1, 9, 30, tzinfo=dt.UTC),
    )
    line = render_line(cap, ZoneInfo("UTC"))
    assert line.startswith("7  ")
    assert "09:30" in line
    assert "abcd1234" in line  # id-prefix
    assert "a summary" in line  # summary wins over content
    assert "#cash-investment" in line  # tag normalized + chipped
    assert "#alpha" in line


def test_render_line_falls_back_to_content() -> None:
    import datetime as dt
    from zoneinfo import ZoneInfo

    cap = Capture(
        id="ffff0000-0000-0000-0000-000000000000",
        seq=1,
        content="first content line\nsecond",
        summary=None,
        tags=(),
        created_at=dt.datetime(2026, 6, 1, 0, 0, tzinfo=dt.UTC),
    )
    line = render_line(cap, ZoneInfo("UTC"))
    assert "first content line" in line
    assert "second" not in line  # only the first non-empty line
