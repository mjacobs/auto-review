"""Postgres connection helper. Uses psycopg v3.

Adapted from agent-review/src/agent_review/db.py (repo convention is
independent siblings, no shared library). Connects as the `memex_sync` role
via PG_DSN; an omitted password is resolved from a repo-local `.pgpass` or
`~/.pgpass` (libpq format), explicit DSN passwords win.
"""

from __future__ import annotations

import getpass
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import psycopg
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.rows import dict_row

from .config import get_settings


@contextmanager
def connect() -> Iterator[psycopg.Connection]:
    """Short-lived connection. Default row factory: dict_row.

    psycopg's connection context commits on clean exit and rolls back on
    exception — sync.py leans on that for its one-transaction-per-run shape.
    """
    dsn = _dsn_with_pgpass_password(get_settings().pg_dsn.get_secret_value())
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        yield conn


def _dsn_with_pgpass_password(dsn: str) -> str:
    """Return DSN with a `.pgpass` password added when the DSN omits one.

    libpq normally reads ``~/.pgpass`` by itself, but this project also supports
    a repo-local ``.pgpass`` (gitignored) for convenience. Explicit passwords in
    ``PG_DSN`` always win.
    """
    conninfo = conninfo_to_dict(dsn)
    if conninfo.get("password"):
        return dsn

    password = _find_pgpass_password(conninfo)
    if password is None:
        return dsn

    return make_conninfo(dsn, password=password)


def _find_pgpass_password(conninfo: dict[str, str]) -> str | None:
    host = _first_csv(conninfo.get("host")) or "localhost"
    port = _first_csv(conninfo.get("port")) or "5432"
    user = conninfo.get("user") or getpass.getuser()
    dbname = conninfo.get("dbname") or user

    for path in _pgpass_candidates():
        password = _read_pgpass_password(path, host=host, port=port, dbname=dbname, user=user)
        if password is not None:
            return password
    return None


def _pgpass_candidates() -> list[Path]:
    """Return passfile candidates in priority order.

    ``PGPASSFILE`` mirrors libpq behavior. A repo-local ``.pgpass`` is checked
    next, then the standard ``~/.pgpass`` location.
    """
    if passfile := os.environ.get("PGPASSFILE"):
        return [Path(passfile).expanduser()]

    candidates = [Path(".pgpass"), Path.home() / ".pgpass"]
    seen: set[Path] = set()
    unique: list[Path] = []
    for candidate in candidates:
        key = candidate.expanduser().resolve(strict=False)
        if key not in seen:
            seen.add(key)
            unique.append(candidate)
    return unique


def _read_pgpass_password(
    path: Path,
    *,
    host: str,
    port: str,
    dbname: str,
    user: str,
) -> str | None:
    if not path.is_file():
        return None

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None

    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        fields = _split_pgpass_line(line)
        if fields is None:
            continue
        entry_host, entry_port, entry_dbname, entry_user, password = fields
        if (
            _pgpass_field_matches(entry_host, host)
            and _pgpass_field_matches(entry_port, port)
            and _pgpass_field_matches(entry_dbname, dbname)
            and _pgpass_field_matches(entry_user, user)
        ):
            return password
    return None


def _split_pgpass_line(line: str) -> tuple[str, str, str, str, str] | None:
    """Split a .pgpass line, honoring backslash-escaped ':' and '\\'."""
    fields: list[str] = []
    current: list[str] = []
    escaped = False

    for char in line:
        if escaped:
            current.append(char)
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == ":":
            fields.append("".join(current))
            current = []
            continue
        current.append(char)

    if escaped:
        current.append("\\")
    fields.append("".join(current))

    if len(fields) != 5:
        return None
    return fields[0], fields[1], fields[2], fields[3], fields[4]


def _pgpass_field_matches(pattern: str, value: str) -> bool:
    return pattern == "*" or pattern == value


def _first_csv(value: str | None) -> str | None:
    if not value:
        return None
    return value.split(",", 1)[0]
