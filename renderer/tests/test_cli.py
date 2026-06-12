"""CLI tests over the fake PG store (CliRunner; no live DB, tmp vault)."""

from __future__ import annotations

import datetime as dt

from click.testing import CliRunner

from checkin_renderer.cli import main
from tests.conftest import make_agent_row, make_capture_row

DATE = dt.date(2026, 6, 10)


def _seed(store) -> None:
    store.captures.append(
        make_capture_row("01:01", summary="an idea.", tags=("idea",), capture_id="c1")
    )
    store.agent_reports[DATE] = make_agent_row(
        narrative_md=(
            "## agent-review — 2026-06-11 00:23\n\nlegacy body\n\n"
            "<!-- agent-review:report_date=2026-06-10 generated_at=x -->\n"
        )
    )


def test_run_dry_run_print_writes_nothing(settings, store):
    _seed(store)
    result = CliRunner().invoke(main, ["run", "2026-06-10", "--dry-run", "--print"])
    assert result.exit_code == 0, result.output
    assert "<!-- checkin-renderer:begin daily=2026-06-10 -->" in result.output
    assert "## memex — 2026-06-10 — inbox" in result.output
    assert "- 01:01 — an idea. `[#idea]`" in result.output
    assert "legacy body" in result.output
    assert "agent-review:report_date=" not in result.output  # legacy marker normalized away
    assert not settings.checkin_path(DATE).exists()
    assert store.job_runs == []


def test_run_writes_note_and_records_ok_run(settings, store):
    _seed(store)
    result = CliRunner().invoke(main, ["run", "2026-06-10"])
    assert result.exit_code == 0, result.output

    text = settings.checkin_path(DATE).read_text(encoding="utf-8")
    assert "checkin-renderer:begin daily=2026-06-10" in text

    assert len(store.job_runs) == 1
    row = store.job_runs[0]
    assert row["status"] == "ok"
    assert row["summary"]["date"] == "2026-06-10"
    assert row["summary"]["mode"] == "bracket"
    assert row["summary"]["sections"] == {
        "memex": {"captures": 1},
        "agent": {"row": True, "legacy": True},
    }
    assert row["summary"]["note_path"] == str(settings.checkin_path(DATE))


def test_run_records_error_row_and_propagates(settings, store):
    _seed(store)
    store.fail_queries = True
    result = CliRunner().invoke(main, ["run", "2026-06-10"])
    assert result.exit_code != 0
    assert len(store.job_runs) == 1
    row = store.job_runs[0]
    assert row["status"] == "error"
    assert "RuntimeError" in row["summary"]["error"]
    assert not settings.checkin_path(DATE).exists()


def test_run_dry_run_records_no_error_row_on_failure(settings, store):
    store.fail_queries = True
    result = CliRunner().invoke(main, ["run", "2026-06-10", "--dry-run"])
    assert result.exit_code != 0
    assert store.job_runs == []


def test_run_full_mode_is_refused(settings, store):
    result = CliRunner().invoke(main, ["run", "2026-06-10", "--mode", "full"])
    assert result.exit_code != 0
    assert store.job_runs == []


def test_run_date_range_renders_each_day(settings, store):
    _seed(store)
    result = CliRunner().invoke(main, ["run", "2026-06-09..2026-06-10"])
    assert result.exit_code == 0, result.output
    assert settings.checkin_path(dt.date(2026, 6, 9)).exists()
    assert settings.checkin_path(DATE).exists()
    assert len(store.job_runs) == 2


def test_missing_agent_row_renders_placeholder(settings, store):
    result = CliRunner().invoke(main, ["run", "2026-06-10", "--dry-run", "--print"])
    assert result.exit_code == 0, result.output
    assert "_no agent-review report row for 2026-06-10_" in result.output
    assert "_no captures in window_" in result.output


def test_weekly_and_monthly_are_phase_stubs(settings, store):
    assert CliRunner().invoke(main, ["run-weekly"]).exit_code != 0
    assert CliRunner().invoke(main, ["run-monthly"]).exit_code != 0


def test_show_prints_bracket_after_run(settings, store):
    _seed(store)
    CliRunner().invoke(main, ["run", "2026-06-10"])
    result = CliRunner().invoke(main, ["show", "2026-06-10"])
    assert result.exit_code == 0, result.output
    assert result.output.startswith("<!-- checkin-renderer:begin daily=2026-06-10 -->")


def test_show_missing_note_exits_2(settings, store):
    result = CliRunner().invoke(main, ["show", "2026-06-10"])
    assert result.exit_code == 2


def test_sections_reports_row_availability(settings, store):
    _seed(store)
    result = CliRunner().invoke(main, ["sections", "2026-06-10"])
    assert result.exit_code == 0, result.output
    assert "memex:    1 capture(s) in window" in result.output
    assert "agent:    row present (legacy full-section format; will normalize)" in result.output
    assert "vault:" in result.output
    assert "health:" in result.output
    assert "projects:" in result.output
