"""Core triage operations: the inbox read + the state flip.

Pulled out of cli.py so the click layer stays thin and the behavior is testable
against the in-memory fake (tests/conftest.py) without a live DSN. Two SQL
statements only (queries.py): a state-filtered listing and a single-row UPDATE.

The flip resolves the human-visible identifier (the monotonic `seq`, or an
id-prefix) to the capture id and runs SQL_SET_STATE inside one transaction. It
never INSERTs — the triage row is seeded 'untriaged' by the sync job, and the
`memex_triage` role has UPDATE-only on capture_triage (0005_roles.sql).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from . import db
from .queries import SQL_INBOX, SQL_RESOLVE_INDEX, SQL_SET_STATE

# connect() seam: any zero-arg callable yielding a psycopg-shaped connection
# context manager (tests pass a fake; production default is db.connect).
ConnectFn = Callable[[], object]

VALID_STATES = ("untriaged", "filed", "discarded")


class UnknownCaptureError(LookupError):
    """A user-supplied seq / id-prefix matched no capture (or was ambiguous)."""


@dataclass(frozen=True)
class Capture:
    """One row of the inbox listing."""

    id: str
    seq: int
    content: str
    summary: str | None
    tags: tuple[str, ...]
    created_at: object  # datetime; kept loose so the fake can pass a stdlib one

    @classmethod
    def from_row(cls, row: dict) -> Capture:
        return cls(
            id=row["id"],
            seq=int(row["seq"]),
            content=row["content"] or "",
            summary=row["summary"],
            tags=tuple(row["tags"] or ()),
            created_at=row["created_at"],
        )


def list_inbox(
    state: str = "untriaged",
    *,
    connect: ConnectFn | None = None,
) -> list[Capture]:
    """Captures in `state`, ordered by seq (the order the human scans)."""
    connect = connect or db.connect
    with connect() as conn, conn.cursor() as cur:
        cur.execute(SQL_INBOX, {"state": state})
        return [Capture.from_row(r) for r in cur.fetchall()]


def set_states(
    seqs: Sequence[str],
    state: str,
    *,
    connect: ConnectFn | None = None,
) -> list[tuple[str, str]]:
    """Flip every identifier in `seqs` to `state` in one transaction.

    Each identifier is the human-visible seq (e.g. "12") or an id-prefix; it is
    resolved against the captures table, then SQL_SET_STATE runs for the
    resolved capture id. Returns (token, capture_id) pairs in input order so the
    caller can echo `<token> -> <state>`. Raises UnknownCaptureError (rolling
    the whole batch back) if any identifier resolves to no/multiple captures.
    """
    if state not in VALID_STATES:
        raise ValueError(f"invalid state {state!r}; expected one of {VALID_STATES}")

    connect = connect or db.connect
    resolved: list[tuple[str, str]] = []
    with connect() as conn:
        # Build the seq/id -> capture_id index once from the captures table.
        index = _capture_index(conn)
        for token in seqs:
            capture_id = _resolve(token, index)
            with conn.cursor() as cur:
                cur.execute(SQL_SET_STATE, {"state": state, "id": capture_id})
            resolved.append((token, capture_id))
    return resolved


def _capture_index(conn) -> dict:
    """A lookup of every capture by seq (as str) and by id, for resolution.

    Read across all states (via the lightweight (id, seq) resolution query) so
    resolution works regardless of a capture's current triage state (re-filing
    a discarded item, etc.). SQL_RESOLVE_INDEX mirrors SQL_INBOX's state filter
    but skips the content/summary payload resolution never reads.
    """
    index: dict[str, str] = {}
    ids: list[str] = []
    for st in VALID_STATES:
        with conn.cursor() as cur:
            cur.execute(SQL_RESOLVE_INDEX, {"state": st})
            for row in cur.fetchall():
                cid = row["id"]
                index[str(row["seq"])] = cid
                ids.append(cid)
    index["__ids__"] = ids  # type: ignore[assignment]
    return index


def _resolve(token: str, index: dict) -> str:
    """Resolve a seq (exact) or an id-prefix to a single capture id."""
    if token in index and token != "__ids__":
        return index[token]

    ids: list[str] = index.get("__ids__", [])  # type: ignore[assignment]
    matches = [cid for cid in ids if cid.startswith(token)]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise UnknownCaptureError(f"no capture matches {token!r} (unknown seq or id-prefix)")
    raise UnknownCaptureError(f"{token!r} is ambiguous: matches {len(matches)} capture ids")
