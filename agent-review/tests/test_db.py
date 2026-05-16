"""Tests for agent_review.db connection helpers."""

from psycopg.conninfo import conninfo_to_dict

from agent_review.db import _dsn_with_pgpass_password, _split_pgpass_line


def test_explicit_dsn_password_wins(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".pgpass").write_text(
        "db.example.com:5432:agentsview:admin:pgpass-secret\n",
        encoding="utf-8",
    )

    dsn = "postgresql://admin:explicit-secret@db.example.com:5432/agentsview"

    assert conninfo_to_dict(_dsn_with_pgpass_password(dsn))["password"] == "explicit-secret"


def test_repo_local_pgpass_used_when_dsn_has_no_password(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".pgpass").write_text(
        "db.example.com:5432:agentsview:admin:pgpass-secret\n",
        encoding="utf-8",
    )

    dsn = "postgresql://admin@db.example.com:5432/agentsview"

    assert conninfo_to_dict(_dsn_with_pgpass_password(dsn))["password"] == "pgpass-secret"


def test_pgpassfile_env_is_preferred_over_repo_local_pgpass(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".pgpass").write_text(
        "db.example.com:5432:agentsview:admin:repo-secret\n",
        encoding="utf-8",
    )
    passfile = tmp_path / "custom.pgpass"
    passfile.write_text(
        "db.example.com:5432:agentsview:admin:env-secret\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("PGPASSFILE", str(passfile))

    dsn = "postgresql://admin@db.example.com:5432/agentsview"

    assert conninfo_to_dict(_dsn_with_pgpass_password(dsn))["password"] == "env-secret"


def test_pgpass_wildcards_and_first_match(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".pgpass").write_text(
        "other.example.com:5432:agentsview:admin:wrong-secret\n"
        "*:5432:agentsview:admin:wildcard-secret\n"
        "db.example.com:5432:agentsview:admin:too-late\n",
        encoding="utf-8",
    )

    dsn = "postgresql://admin@db.example.com:5432/agentsview"

    assert conninfo_to_dict(_dsn_with_pgpass_password(dsn))["password"] == "wildcard-secret"


def test_no_matching_pgpass_leaves_dsn_passwordless(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".pgpass").write_text(
        "other.example.com:5432:agentsview:admin:wrong-secret\n",
        encoding="utf-8",
    )

    dsn = "postgresql://admin@db.example.com:5432/agentsview"

    assert "password" not in conninfo_to_dict(_dsn_with_pgpass_password(dsn))


def test_pgpass_escaped_colon_and_backslash_are_unescaped():
    fields = _split_pgpass_line(r"db.example.com:5432:agents\:view:adm\\in:s3\:cr\\et")

    assert fields == (
        "db.example.com",
        "5432",
        "agents:view",
        r"adm\in",
        r"s3:cr\et",
    )
