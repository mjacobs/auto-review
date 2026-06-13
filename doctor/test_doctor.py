"""Tests for auto-review-doctor v0.

The script ships as a single executable file with no .py extension, so load it
by path via importlib. Run with: `python3 -m pytest doctor/test_doctor.py` (or
`python3 doctor/test_doctor.py` for the lightweight asserts at the bottom).
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import sys
import tempfile
from importlib.machinery import SourceFileLoader
from pathlib import Path

_path = Path(__file__).with_name("auto-review-doctor")
_loader = SourceFileLoader("auto_review_doctor", str(_path))
_spec = importlib.util.spec_from_loader(_loader.name, _loader)
doctor = importlib.util.module_from_spec(_spec)
sys.modules[_loader.name] = doctor  # @dataclass resolves cls.__module__ here
_loader.exec_module(doctor)


# ─── week-label math ──────────────────────────────────────────────────────────


def test_reported_week_label_is_last_week():
    # Monday 2026-05-25 is in ISO week 2026-W22; the weekly cron runs
    # `last-week` on Monday, so the recap it writes covers the just-ended
    # 2026-W21 (Mon–Sun).
    assert doctor.iso_week_label(dt.date(2026, 5, 25)) == "2026-W22"
    assert doctor.reported_week_label(dt.date(2026, 5, 25)) == "2026-W21"


def test_weekly_note_path_uses_reported_label():
    p = doctor.weekly_note_path(Path("/v"), "2026-W21")
    assert p == Path("/v/journal/weekly/2026-W21.md")


# ─── section_info: weekly (the auto-review-87e regression) ─────────────────────

WEEKLY_NOTE = """\
---
tags: [journal/weekly]
---
# week of 2026-05-18

## vault-review weekly — 2026-W21

_window: 2026-05-18 → 2026-05-24_

- shipped the doctor v0
- closed three beads

<!-- vault-review:weekly=2026-W21 generated_at=2026-05-31T17:01:01Z -->
"""


def test_section_info_weekly_present():
    present, lines, note = doctor.section_info(
        WEEKLY_NOTE, "vault-review", "weekly", "2026-W21"
    )
    assert present is True
    assert lines >= 3  # window line + two bullets, blanks ignored
    assert note == ""


def test_section_info_weekly_wrong_label_absent():
    # Looking for the *current* week (the pre-fix bug) must report missing.
    present, lines, _ = doctor.section_info(
        WEEKLY_NOTE, "vault-review", "weekly", "2026-W22"
    )
    assert present is False
    assert lines == 0


# ─── section_info: daily (must still work after the refactor) ──────────────────

DAILY_NOTE = """\
# check-in — 2026-05-30

## vault-review — 2026-05-30

- one
- two

<!-- vault-review:daily=2026-05-30 generated_at=2026-05-31T03:01:01Z -->

## memex-review — 2026-05-30 — inbox

nothing today

<!-- memex-review:daily=2026-05-30 generated_at=2026-05-31T03:31:01Z -->
"""


def test_section_info_daily_present_and_scoped_per_tool():
    v_present, v_lines, _ = doctor.section_info(
        DAILY_NOTE, "vault-review", "daily", "2026-05-30"
    )
    assert v_present is True and v_lines == 2

    m_present, m_lines, _ = doctor.section_info(
        DAILY_NOTE, "memex-review", "daily", "2026-05-30"
    )
    assert m_present is True and m_lines == 1


# ─── assess_jobs: full weekly path on a Monday ────────────────────────────────


def test_assess_jobs_weekly_present_on_monday():
    # Monday 2026-05-25 → last-week = 2026-W21, the label WEEKLY_NOTE carries.
    monday = dt.date(2026, 5, 25)
    log = ["[main deadbee] vault-review: weekly recap 2026-05-25T17:01:01Z\n"]
    reports = doctor.assess_jobs(log, monday, yesterday_checkin_text="", weekly_text=WEEKLY_NOTE, tracebacks=[])
    weekly = next(r for r in reports if r.name == "vault-review weekly")
    assert weekly.skipped_reason is None  # Monday → not skipped
    assert weekly.fired is True
    assert weekly.section_present is True
    assert weekly.section_lines >= 3


def test_assess_jobs_weekly_skipped_midweek():
    thursday = dt.date(2026, 5, 28)
    reports = doctor.assess_jobs([], thursday, yesterday_checkin_text="", weekly_text="", tracebacks=[])
    weekly = next(r for r in reports if r.name == "vault-review weekly")
    assert weekly.skipped_reason == "weekly — Mondays only"


def test_find_tracebacks_empty():
    assert doctor.find_tracebacks([]) == []


def test_find_tracebacks_parses_real_traceback():
    log = [
        "Some random log line\n",
        "Traceback (most recent call last):\n",
        "  File \"/home/mj/.local/share/pipx/venvs/memex-review/lib/python3.10/site-packages/memex_review/client.py\", line 45, in get_thoughts\n",
        "    raise HTTPError(res.status_code, res.text)\n",
        "urllib.error.HTTPError: HTTP Error 500: Internal Server Error\n",
        "Another log line\n"
    ]
    tbs = doctor.find_tracebacks(log)
    assert len(tbs) == 1
    assert tbs[0]["tool"] == "memex-review"
    assert tbs[0]["summary"] == "HTTPError: HTTP Error 500: Internal Server Error (client.py:45)"


def test_assess_jobs_reports_crash():
    log = [
        "Traceback (most recent call last):\n",
        "  File \"/home/mj/.local/share/uv/tools/vault-review/lib/python3.13/site-packages/vault_review/gitdelta.py\", line 45, in collect\n",
        "    raise HTTPError(res.status_code, res.text)\n",
        "urllib.error.HTTPError: HTTP Error 500: Internal Server Error\n",
    ]
    tbs = doctor.find_tracebacks(log)
    reports = doctor.assess_jobs(log, dt.date(2026, 5, 31), "", "", tbs)
    vr = next(r for r in reports if r.name == "vault-review daily")
    assert vr.fired is False
    assert len(vr.tracebacks) == 1
    assert "HTTPError" in vr.tracebacks[0]


def test_section_info_agent_review_daily_present():
    note = """\
# check-in — 2026-05-30

## agent-review — 2026-05-30

- did some work
- agent was busy

<!-- agent-review:report_date=2026-05-30 generated_at=2026-05-31T04:01:01Z -->
"""
    present, lines, note_str = doctor.section_info(
        note, "agent-review", "report_date", "2026-05-30"
    )
    assert present is True
    assert lines == 2
    assert note_str == ""


def test_assess_jobs_pg_writers_now_monitored():
    # hg6.8 re-monitors the PG writers via ops.job_runs. With no pg_runs (PG
    # unreachable) they surface as degraded reports rather than being skipped;
    # memex-review is gone entirely; the marker jobs are unaffected. An
    # agent-review commit line in the log is now irrelevant — it's a PG job.
    today = dt.date(2026, 5, 31)
    log = ["[main deadbee] agent-review: daily report 2026-05-31T21:01:01Z\n"]
    reports = doctor.assess_jobs(log, today, yesterday_checkin_text="", weekly_text="", tracebacks=[])
    by_name = {r.name: r for r in reports}
    assert "memex-review daily" not in by_name        # dissolved (hg6.4)
    assert "vault-review daily" in by_name             # marker job, unaffected
    for pg_name in ("agent-review daily", "check-in renderer daily", "memex-sync hourly"):
        assert by_name[pg_name].pg is True
        assert by_name[pg_name].pg_status == "degraded"  # pg_runs defaulted to None


def test_assess_jobs_weekly_present_on_monday_with_reported_label():
    # Tests that when we run on a Monday, the weekly section is looked up with
    # the correct reported_week_label and weekly marker-key, and is found.
    monday = dt.date(2026, 5, 25)
    log = ["[main deadbee] vault-review: weekly recap 2026-05-25T17:01:01Z\n"]
    reports = doctor.assess_jobs(
        log, monday, yesterday_checkin_text="", weekly_text=WEEKLY_NOTE, tracebacks=[]
    )
    weekly = next(r for r in reports if r.name == "vault-review weekly")
    assert weekly.skipped_reason is None
    assert weekly.fired is True
    assert weekly.section_present is True
    assert weekly.section_lines >= 3


# ─── self-liveness: the doctor monitoring its own missed runs (g52) ────────────


def _write_doctor_checkins(checkin_dir: Path, dates: list[dt.date]) -> None:
    """Write a minimal check-in note carrying the doctor's own close-marker for
    each given date."""
    checkin_dir.mkdir(parents=True, exist_ok=True)
    for d in dates:
        iso = d.isoformat()
        path = doctor.checkin_path(checkin_dir, d)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            f"# check-in — {iso}\n\n## auto-review doctor — {iso}\n\n"
            f"<!-- auto-review-doctor:daily={iso} generated_at={iso}T22:01:00Z -->\n",
            encoding="utf-8",
        )


def test_doctor_self_liveness_no_gaps():
    today = dt.date(2026, 6, 5)
    with tempfile.TemporaryDirectory() as tmp:
        checkin_dir = Path(tmp) / "checkins"
        # doctor section present every prior day in the window
        _write_doctor_checkins(checkin_dir, [today - dt.timedelta(days=n) for n in range(1, 5)])
        last_present, gaps = doctor.doctor_self_liveness(checkin_dir, today)
    assert last_present == today - dt.timedelta(days=1)
    assert gaps == []


def test_doctor_self_liveness_detects_consecutive_gap():
    # The motivating incident: doctor ran 3 days ago, then silently missed the
    # next two nights. Surfaced the moment it runs again.
    today = dt.date(2026, 6, 5)
    with tempfile.TemporaryDirectory() as tmp:
        checkin_dir = Path(tmp) / "checkins"
        _write_doctor_checkins(checkin_dir, [today - dt.timedelta(days=3)])
        last_present, gaps = doctor.doctor_self_liveness(checkin_dir, today)
    assert last_present == today - dt.timedelta(days=3)
    assert gaps == [today - dt.timedelta(days=2), today - dt.timedelta(days=1)]


def test_doctor_self_liveness_no_prior_runs_is_quiet_on_pre_existence():
    today = dt.date(2026, 6, 5)
    with tempfile.TemporaryDirectory() as tmp:
        checkin_dir = Path(tmp) / "checkins"
        checkin_dir.mkdir()
        last_present, gaps = doctor.doctor_self_liveness(checkin_dir, today)
    assert last_present is None
    assert gaps == []  # don't flag days before the doctor ever ran


def test_format_self_liveness_variants():
    today = dt.date(2026, 6, 5)
    healthy = doctor.format_self_liveness(today, today - dt.timedelta(days=1), [])
    assert "no gaps" in healthy and "⚠️" not in healthy
    gapped = doctor.format_self_liveness(
        today, today - dt.timedelta(days=3), [today - dt.timedelta(days=2)]
    )
    assert "⚠️" in gapped and "2026-06-03" in gapped
    never = doctor.format_self_liveness(today, None, [])
    assert "⚠️" in never and "ever run" in never


def test_assess_jobs_doctor_self_row_reflects_real_yesterday_section():
    today = dt.date(2026, 5, 31)
    # yesterday's check-in is MISSING the doctor's own section
    yesterday_text = "# check-in — 2026-05-30\n\n## vault-review — 2026-05-30\n"
    reports = doctor.assess_jobs(
        [], today, yesterday_checkin_text=yesterday_text, weekly_text="", tracebacks=[]
    )
    doc = next(r for r in reports if r.name == "auto-review-doctor daily")
    assert doc.fired is True  # this very run
    assert doc.section_present is False  # honestly reports yesterday's gap

    # now with yesterday's doctor section present
    present_text = (
        "# check-in — 2026-05-30\n\n## auto-review doctor — 2026-05-30\n\n"
        "- all good\n\n<!-- auto-review-doctor:daily=2026-05-30 generated_at=2026-05-31T05:01:00Z -->\n"
    )
    reports2 = doctor.assess_jobs(
        [], today, yesterday_checkin_text=present_text, weekly_text="", tracebacks=[]
    )
    doc2 = next(r for r in reports2 if r.name == "auto-review-doctor daily")
    assert doc2.section_present is True
    # The spaced heading "## auto-review doctor" must match the hyphenated marker
    # tool, so the body line count is real (not the "open heading missing" wart).
    assert doc2.section_lines == 1
    assert "open heading missing" not in doc2.section_note


# ─── moving-pieces registry (9nr) ──────────────────────────────────────────────


def test_registry_monitored_jobs_have_liveness_config():
    # Every monitored job carries EXACTLY ONE liveness config: the marker path
    # (commit_regex + marker + hhmm — vault-review, doctor self) or the PG path
    # (pg_job_name + interval — the job_runs writers, hg6.8). Unmonitored infra
    # pretends to have neither.
    for j in doctor.JOBS:
        marker = bool(j.commit_regex and j.marker_tool and j.marker_key and j.hhmm)
        pg = bool(j.pg_job_name and j.pg_interval_hours > 0)
        if j.monitored:
            assert marker ^ pg, f"{j.name}: monitored needs exactly one of marker/PG config"
        else:
            assert not marker and not pg, f"{j.name}: unmonitored but has liveness config"
            assert j.commit_regex is None and not j.marker_tool and not j.pg_job_name


def test_registry_has_both_monitored_and_coverage_gaps():
    monitored = [j for j in doctor.JOBS if j.monitored]
    gaps = [j for j in doctor.JOBS if not j.monitored]
    # 6 monitored after hg6.8: 3 marker (vault-review daily+weekly, doctor) + 3
    # PG (memex-sync, agent-review, renderer). Gaps remain (off-host infra etc).
    assert len(monitored) >= 6
    assert len(gaps) >= 1  # the whole point: catalog what ISN'T watched


def test_render_moving_pieces_lists_all_with_coverage_flags():
    today = dt.date(2026, 6, 5)
    doc = doctor.render_moving_pieces(today)
    # every registry entry appears
    for j in doctor.JOBS:
        assert j.name in doc, f"{j.name} missing from moving-pieces doc"
    assert "✅" in doc and "⚠️ no" in doc  # both monitored and gap rows rendered
    assert "DO NOT EDIT BY HAND" in doc
    assert "auto-review-doctor:moving-pieces" in doc  # close marker for idempotent rewrite


# ─── PG liveness path (auto-review-hg6.8) ─────────────────────────────────────

# 2026-06-13 08:31 UTC ≈ 00:31 PT — when the doctor cron fires.
NOW = dt.datetime(2026, 6, 13, 8, 31, 0, tzinfo=dt.timezone.utc)


def _runrow(job_name: str, finished: dt.datetime, status: str = "ok", cost=None):
    return doctor.RunRow(job_name=job_name, finished_at=finished, status=status, cost_usd=cost)


def _pg_reports(pg_runs, today=dt.date(2026, 6, 13)):
    return doctor.assess_jobs([], today, "", "", [], pg_runs=pg_runs, now_utc=NOW)


def test_rows_to_runmap_parses_and_skips_malformed():
    rows = [
        ["memex-sync", "2026-06-13T21:41:01Z", "ok", ""],          # NULL cost -> None
        ["agent-review", "2026-06-13T07:21:00Z", "ok", "0.1234"],
        ["bad-ts", "not-a-date", "ok", ""],                        # skipped: bad timestamp
        ["too-few"],                                               # skipped: < 4 fields
    ]
    m = doctor._rows_to_runmap(rows)
    assert set(m) == {"memex-sync", "agent-review"}
    assert m["memex-sync"].cost_usd is None
    assert m["agent-review"].cost_usd == 0.1234
    assert m["agent-review"].status == "ok"


def test_query_latest_runs_degrades_without_dsn():
    # No DSN -> None (the doctor falls back to log/marker), never raises.
    assert doctor.query_latest_runs(None) is None
    assert doctor.query_latest_runs("") is None


def test_assess_pg_job_fresh_with_cost():
    runs = {"agent-review": _runrow("agent-review", NOW - dt.timedelta(minutes=10), cost=0.05)}
    ar = next(r for r in _pg_reports(runs) if r.name == "agent-review daily")
    assert ar.pg and ar.fired and not ar.pg_overdue
    assert ar.pg_status == "ok"
    assert ar.pg_cost == "$0.0500"
    assert ar.fired_at_pt == "01:21"  # 08:21 UTC -> 01:21 PT, today


def test_assess_pg_job_renderer_day_old_row_is_fresh():
    # The renderer (00:51) runs AFTER the 00:31 doctor, so its freshest row is
    # ~24h old at doctor time — still within the 26h window, not overdue.
    finished = NOW - dt.timedelta(hours=23, minutes=40)
    runs = {"checkin-renderer-daily": _runrow("checkin-renderer-daily", finished)}
    rr = next(r for r in _pg_reports(runs) if r.name == "check-in renderer daily")
    assert rr.fired and not rr.pg_overdue
    assert rr.fired_at_pt == "(2026-06-12)"


def test_assess_pg_job_overdue_when_stale():
    runs = {"checkin-renderer-daily": _runrow("checkin-renderer-daily", NOW - dt.timedelta(days=3))}
    rr = next(r for r in _pg_reports(runs) if r.name == "check-in renderer daily")
    assert rr.pg and not rr.fired and rr.pg_overdue
    assert rr.fired_at_pt == "(2026-06-10)"


def test_assess_pg_job_never_ran():
    ms = next(r for r in _pg_reports({}) if r.name == "memex-sync hourly")
    assert ms.pg and not ms.fired and ms.fired_at_pt is None
    assert ms.pg_status is None  # no row at all


def test_assess_pg_job_degraded_without_pg():
    ms = next(r for r in _pg_reports(None) if r.name == "memex-sync hourly")
    assert ms.pg and ms.pg_status == "degraded" and not ms.fired


def test_assess_pg_job_surfaces_error_status():
    runs = {"memex-sync": _runrow("memex-sync", NOW - dt.timedelta(minutes=20), status="error")}
    ms = next(r for r in _pg_reports(runs) if r.name == "memex-sync hourly")
    assert ms.fired  # ran 20 min ago, within the 2h hourly window
    assert ms.pg_status == "error"


def test_render_section_degraded_shows_banner_and_unknown():
    today = dt.date(2026, 6, 13)
    reports = _pg_reports(None, today)
    out = doctor.render_section(today, reports, [], 0, (today - dt.timedelta(days=1), []))
    assert "PG liveness unavailable" in out
    assert "unknown (no PG)" in out
    assert "jobs healthy" in out


def test_render_section_pg_fresh_shows_status_and_cost():
    today = dt.date(2026, 6, 13)
    runs = {
        "agent-review": _runrow("agent-review", NOW - dt.timedelta(minutes=10), cost=0.05),
        "memex-sync": _runrow("memex-sync", NOW - dt.timedelta(minutes=20)),
        "checkin-renderer-daily": _runrow(
            "checkin-renderer-daily", NOW - dt.timedelta(hours=23, minutes=40)
        ),
    }
    reports = _pg_reports(runs, today)
    out = doctor.render_section(today, reports, [], 0, (today - dt.timedelta(days=1), []))
    assert "PG liveness unavailable" not in out
    assert "$0.0500" in out
    assert "✓ ok" in out
    assert "| last run | latest result |" in out


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} passed")

