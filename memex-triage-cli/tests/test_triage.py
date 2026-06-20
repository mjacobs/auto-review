"""Core triage behavior against the in-memory fake PG layer (see conftest)."""

from __future__ import annotations

import pytest

from memex_triage_cli.triage import UnknownCaptureError, list_inbox, set_states

from .conftest import FakeStore, make_capture


def test_list_inbox_returns_seq_ordered_untriaged(store: FakeStore) -> None:
    store.seed(
        make_capture(3),
        make_capture(1),
        make_capture(2, state="filed"),  # excluded: different state
    )
    rows = list_inbox("untriaged", connect=store.connect)

    assert [c.seq for c in rows] == [1, 3]  # seq-ordered, filed one dropped
    assert all(isinstance(c.id, str) for c in rows)


def test_list_inbox_filters_by_state(store: FakeStore) -> None:
    store.seed(make_capture(1), make_capture(2, state="discarded"))
    assert [c.seq for c in list_inbox("discarded", connect=store.connect)] == [2]


def test_file_sets_state_filed_on_resolved_capture(store: FakeStore) -> None:
    store.seed(make_capture(12))
    resolved = set_states(["12"], "filed", connect=store.connect)

    assert store.state_of(12) == "filed"
    # seq 12 resolved to the real capture id
    assert resolved == [("12", make_capture(12)["id"])]


def test_discard_and_reset_round_trip(store: FakeStore) -> None:
    store.seed(make_capture(5))
    set_states(["5"], "discarded", connect=store.connect)
    assert store.state_of(5) == "discarded"
    set_states(["5"], "untriaged", connect=store.connect)
    assert store.state_of(5) == "untriaged"


def test_set_states_resolves_seq_to_capture_id(store: FakeStore) -> None:
    cap = make_capture(7, capture_id="abcdef12-0000-0000-0000-000000000000")
    store.seed(cap)
    resolved = set_states(["7"], "filed", connect=store.connect)
    assert resolved == [("7", cap["id"])]
    assert store.state_of(7) == "filed"


def test_set_states_resolves_id_prefix(store: FakeStore) -> None:
    cap = make_capture(9, capture_id="deadbeef-1234-5678-9abc-def012345678")
    store.seed(cap)
    set_states(["deadbeef"], "filed", connect=store.connect)
    assert store.state_of(9) == "filed"


def test_unknown_seq_errors_cleanly_and_writes_nothing(store: FakeStore) -> None:
    store.seed(make_capture(1))
    with pytest.raises(UnknownCaptureError, match="no capture matches '999'"):
        set_states(["999"], "filed", connect=store.connect)
    assert store.state_of(1) == "untriaged"  # untouched


def test_ambiguous_prefix_errors(store: FakeStore) -> None:
    store.seed(
        make_capture(1, capture_id="ab000000-0000-0000-0000-000000000000"),
        make_capture(2, capture_id="ab111111-1111-1111-1111-111111111111"),
    )
    with pytest.raises(UnknownCaptureError, match="ambiguous"):
        set_states(["ab"], "filed", connect=store.connect)


def test_batch_flip_rolls_back_entirely_on_unknown_token(store: FakeStore) -> None:
    """A bad token mid-batch must leave every row in the batch untouched."""
    store.seed(make_capture(1), make_capture(2))
    with pytest.raises(UnknownCaptureError):
        set_states(["1", "999", "2"], "filed", connect=store.connect)
    # the whole transaction rolled back
    assert store.state_of(1) == "untriaged"
    assert store.state_of(2) == "untriaged"


def test_set_states_runs_in_one_transaction(store: FakeStore) -> None:
    store.seed(make_capture(1), make_capture(2))
    set_states(["1", "2"], "filed", connect=store.connect)
    assert store.connections_opened == 1  # single connection / transaction
    assert store.state_of(1) == store.state_of(2) == "filed"


def test_invalid_state_rejected(store: FakeStore) -> None:
    store.seed(make_capture(1))
    with pytest.raises(ValueError, match="invalid state"):
        set_states(["1"], "bogus", connect=store.connect)


def test_resolution_spans_states(store: FakeStore) -> None:
    """A discarded capture can be re-filed by seq even though it isn't untriaged."""
    store.seed(make_capture(4, state="discarded"))
    set_states(["4"], "filed", connect=store.connect)
    assert store.state_of(4) == "filed"


def test_resolution_uses_minimal_index_columns(store: FakeStore) -> None:
    """Resolution goes through SQL_RESOLVE_INDEX, which yields only (id, seq).

    The fake's SQL_RESOLVE_INDEX branch returns rows lacking content/summary, so
    these flips passing proves _capture_index resolves by both seq and
    id-prefix without ever reading the heavy payload columns.
    """
    cap = make_capture(8, capture_id="c0ffee00-0000-0000-0000-000000000000")
    store.seed(cap)
    # by seq
    set_states(["8"], "filed", connect=store.connect)
    assert store.state_of(8) == "filed"
    # by id-prefix
    set_states(["c0ffee"], "discarded", connect=store.connect)
    assert store.state_of(8) == "discarded"
