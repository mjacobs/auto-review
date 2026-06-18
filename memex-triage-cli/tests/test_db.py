"""db.py / config.py wiring: DSN alias + .pgpass resolution, no live connection.

These exercise only the pure helpers (password lookup, DSN rewriting) and the
settings alias — never `connect()`, which would open a socket.
"""

from __future__ import annotations

import pytest

from memex_triage_cli import config, db
from memex_triage_cli.config import Settings


@pytest.fixture(autouse=True)
def _reset_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "_settings", None)


def test_pg_dsn_alias_is_memex_triage(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MEMEX_TRIAGE_PG_DSN", "postgresql://memex_triage@db.example:5432/agentsview")
    s = Settings()  # type: ignore[call-arg]
    assert s.pg_dsn.get_secret_value().startswith("postgresql://memex_triage@")


def test_tz_defaults_and_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MEMEX_TRIAGE_PG_DSN", "postgresql://memex_triage@db.example:5432/db")
    monkeypatch.delenv("TZ", raising=False)
    assert Settings().tz_name == "America/Los_Angeles"  # type: ignore[call-arg]
    monkeypatch.setenv("TZ", "UTC")
    config._settings = None
    assert str(Settings().tz) == "UTC"  # type: ignore[call-arg]


def test_explicit_dsn_password_wins() -> None:
    dsn = "postgresql://memex_triage:secret@db.example:5432/agentsview"
    assert db._dsn_with_pgpass_password(dsn) == dsn


def test_pgpass_password_injected_from_repo_local_file(tmp_path, monkeypatch) -> None:
    pgpass = tmp_path / ".pgpass"
    pgpass.write_text("db.example:5432:agentsview:memex_triage:s3cr3t\n", encoding="utf-8")
    monkeypatch.setenv("PGPASSFILE", str(pgpass))

    dsn = "postgresql://memex_triage@db.example:5432/agentsview"
    out = db._dsn_with_pgpass_password(dsn)
    assert "password=s3cr3t" in out


def test_pgpass_wildcards_match(tmp_path, monkeypatch) -> None:
    pgpass = tmp_path / ".pgpass"
    pgpass.write_text("*:*:*:memex_triage:wild\n", encoding="utf-8")
    monkeypatch.setenv("PGPASSFILE", str(pgpass))

    out = db._dsn_with_pgpass_password("postgresql://memex_triage@db.example:5432/agentsview")
    assert "password=wild" in out


def test_pgpass_no_match_leaves_dsn_unchanged(tmp_path, monkeypatch) -> None:
    pgpass = tmp_path / ".pgpass"
    pgpass.write_text("other:5432:db:otheruser:nope\n", encoding="utf-8")
    monkeypatch.setenv("PGPASSFILE", str(pgpass))

    dsn = "postgresql://memex_triage@db.example:5432/agentsview"
    assert db._dsn_with_pgpass_password(dsn) == dsn
