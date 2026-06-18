"""CLI-level wiring of ops.job_runs recording (auto-review-2vv).

The runlog unit tests cover record_job_run in isolation; these confirm cli.py
wires the DAILY and WEEKLY run paths to the right job_name, records on a real
write, skips recording on --dry-run, and records an 'error' row when the section
write fails (best-effort) without swallowing the original error.
"""

from __future__ import annotations

from click.testing import CliRunner

from vault_review import cli


def _seed_vault_commit(tmp_path) -> None:
    """A minimal git vault so collect_events/render_dossier have something to do."""
    import subprocess

    vault = tmp_path / "vault"
    (vault / "journal" / "checkins").mkdir(parents=True)
    (vault / "journal" / "weekly").mkdir(parents=True)
    (vault / "notes").mkdir()
    def run(*a):
        subprocess.run(["git", *a], cwd=vault, check=True, capture_output=True)

    run("init", "-q")
    run("config", "user.email", "t@t.t")
    run("config", "user.name", "t")
    (vault / "notes" / "a.md").write_text("hello\n")
    run("add", "-A")
    run("commit", "-q", "-m", "seed", "--date", "2026-06-15T10:00:00")


def test_daily_run_records_ok_row(settings, store, tmp_path):
    _seed_vault_commit(tmp_path)
    result = CliRunner().invoke(cli.main, ["run", "2026-06-15"])
    assert result.exit_code == 0, result.output
    assert len(store.job_runs) == 1
    row = store.job_runs[0]
    assert row["job_name"] == "vault-review-daily"
    assert row["status"] == "ok"
    assert row["summary"]["date"] == "2026-06-15"
    assert "events" in row["summary"] and "note_path" in row["summary"]


def test_weekly_run_records_ok_row(settings, store, tmp_path):
    _seed_vault_commit(tmp_path)
    result = CliRunner().invoke(cli.main, ["run-weekly", "2026-W25"])
    assert result.exit_code == 0, result.output
    assert len(store.job_runs) == 1
    row = store.job_runs[0]
    assert row["job_name"] == "vault-review-weekly"
    assert row["status"] == "ok"
    assert row["summary"]["week_label"] == "2026-W25"


def test_dry_run_records_no_row(settings, store, tmp_path):
    _seed_vault_commit(tmp_path)
    result = CliRunner().invoke(cli.main, ["run", "2026-06-15", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert store.job_runs == []


def test_daily_write_failure_records_error_row_and_reraises(settings, store, tmp_path, monkeypatch):
    _seed_vault_commit(tmp_path)

    def boom(*a, **k):
        raise RuntimeError("disk full")

    monkeypatch.setattr(cli, "write_daily_section", boom)
    result = CliRunner().invoke(cli.main, ["run", "2026-06-15"])
    assert result.exit_code != 0  # original error propagates
    assert isinstance(result.exception, RuntimeError)
    assert len(store.job_runs) == 1
    assert store.job_runs[0]["status"] == "error"
    assert store.job_runs[0]["job_name"] == "vault-review-daily"
    assert "disk full" in store.job_runs[0]["summary"]["error"]
