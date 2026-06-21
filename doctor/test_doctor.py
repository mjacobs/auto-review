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


# ─── assess_jobs: vault-review is now PG-monitored (auto-review-2vv) ───────────


def test_assess_jobs_vault_review_jobs_are_pg_monitored():
    # vault-review daily AND weekly moved off the log+marker path onto ops.job_runs
    # (auto-review-2vv). With no pg_runs (PG unreachable) both surface as PG
    # degraded reports rather than marker/skipped reports. An old weekly commit
    # line in the log is now irrelevant.
    monday = dt.date(2026, 5, 25)
    log = ["[main deadbee] vault-review: weekly recap 2026-05-25T17:01:01Z\n"]
    reports = doctor.assess_jobs(log, monday, yesterday_checkin_text="", tracebacks=[])
    by_name = {r.name: r for r in reports}
    for name in ("vault-review daily", "vault-review weekly"):
        assert by_name[name].pg is True
        assert by_name[name].pg_status == "degraded"  # pg_runs defaulted to None
        assert by_name[name].skipped_reason is None   # no "Mondays only" skip anymore


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


def test_vault_review_crash_surfaces_in_diagnostics():
    # vault-review is now PG-monitored (auto-review-2vv), so a vault-review crash
    # is no longer attributed per-job in the marker table — but it must still
    # surface: find_tracebacks parses it (attributed to the vault-review tool) and
    # render_section lists it in the "Tracebacks in log tail" diagnostics.
    today = dt.date(2026, 5, 31)
    log = [
        "Traceback (most recent call last):\n",
        "  File \"/home/mj/.local/share/uv/tools/vault-review/lib/python3.13/site-packages/vault_review/gitdelta.py\", line 45, in collect\n",
        "    raise HTTPError(res.status_code, res.text)\n",
        "urllib.error.HTTPError: HTTP Error 500: Internal Server Error\n",
    ]
    tbs = doctor.find_tracebacks(log)
    assert len(tbs) == 1
    assert tbs[0]["tool"] == "vault-review"
    assert "HTTPError" in tbs[0]["summary"]
    reports = doctor.assess_jobs(log, today, "", tbs)
    out = doctor.render_section(today, reports, tbs, 0, (today - dt.timedelta(days=1), []))
    assert "Tracebacks in log tail" in out
    assert "vault-review" in out and "HTTPError" in out


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
    reports = doctor.assess_jobs(log, today, yesterday_checkin_text="", tracebacks=[])
    by_name = {r.name: r for r in reports}
    assert "memex-review daily" not in by_name        # dissolved (hg6.4)
    assert "vault-review daily" in by_name             # now PG-monitored (2vv)
    for pg_name in ("agent-review daily", "check-in renderer daily", "memex-sync hourly"):
        assert by_name[pg_name].pg is True
        assert by_name[pg_name].pg_status == "degraded"  # pg_runs defaulted to None


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
        [], today, yesterday_checkin_text=yesterday_text, tracebacks=[]
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
        [], today, yesterday_checkin_text=present_text, tracebacks=[]
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
    # (commit_regex + marker + hhmm — now only the doctor self-row) or the PG path
    # (pg_job_name + a window — the job_runs writers, hg6.8/2vv). The PG window is
    # either a flat interval (daily) or the schedule-aware weekly check
    # (pg_weekly). Unmonitored infra pretends to have neither.
    for j in doctor.JOBS:
        marker = bool(j.commit_regex and j.marker_tool and j.marker_key and j.hhmm)
        pg = bool(j.pg_job_name and (j.pg_interval_hours > 0 or j.pg_weekly))
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
    return doctor.assess_jobs([], today, "", [], pg_runs=pg_runs, now_utc=NOW)


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
    # The renderer now runs BEFORE the doctor (an earlier phase of the ordered
    # run-checkin-nightly chain, doctor LAST), so on a healthy night its freshest
    # row is minutes old. The 26h window still tolerates a slow/in-flight nightly
    # run that falls back to yesterday's ~24h-old row — modelled here — without
    # flagging overdue.
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


# ─── schedule-aware weekly liveness (auto-review-2vv; absorbs hg6.12 BUG2) ─────
#
# The weekly fires Mon 00:08 PT (= 07:08 UTC in PDT). The old marker+
# reported_week_label path false-positived every Monday in the window BEFORE the
# weekly fired but AFTER the doctor ran (hg6.12 BUG2). The PG check is schedule-
# aware: overdue ONLY once the most-recent expected Monday fire (+grace) has
# passed with no fresh row. These tests pin both the BUG2 non-regression and a
# genuine miss.

WEEKLY = "vault-review-weekly"


def _weekly_report(pg_runs, today, now_utc):
    reports = doctor.assess_jobs([], today, "", [], pg_runs=pg_runs, now_utc=now_utc)
    return next(r for r in reports if r.name == "vault-review weekly")


def test_most_recent_weekly_fire_picks_this_week_after_fire():
    job = next(j for j in doctor.JOBS if j.pg_job_name == WEEKLY)
    # Monday 2026-06-15 00:22 PT = 07:22 UTC — just after the 00:08 fire.
    now = dt.datetime(2026, 6, 15, 7, 22, tzinfo=dt.timezone.utc)
    fire = doctor.most_recent_weekly_fire(job, now)
    # This Monday's 00:08 PT fire = 07:08 UTC.
    assert fire == dt.datetime(2026, 6, 15, 7, 8, tzinfo=dt.timezone.utc)


def test_most_recent_weekly_fire_picks_last_week_before_fire():
    job = next(j for j in doctor.JOBS if j.pg_job_name == WEEKLY)
    # Monday 2026-06-15 00:05 PT = 07:05 UTC — BEFORE the 00:08 fire.
    now = dt.datetime(2026, 6, 15, 7, 5, tzinfo=dt.timezone.utc)
    fire = doctor.most_recent_weekly_fire(job, now)
    # Falls back to LAST Monday's fire (2026-06-08 00:08 PT = 07:08 UTC).
    assert fire == dt.datetime(2026, 6, 8, 7, 8, tzinfo=dt.timezone.utc)


def test_weekly_not_overdue_before_monday_fire_is_the_bug2_case():
    # hg6.12 BUG2: a Monday morning BEFORE the weekly's 00:08 fire must NOT be
    # flagged missing/overdue just because this week's row hasn't landed yet.
    # The latest row is last Monday's normal run; the doctor runs at 00:05 PT.
    monday = dt.date(2026, 6, 15)
    now = dt.datetime(2026, 6, 15, 7, 5, tzinfo=dt.timezone.utc)  # 00:05 PT, pre-fire
    last_week_run = dt.datetime(2026, 6, 8, 7, 9, tzinfo=dt.timezone.utc)  # last Mon 00:09 PT
    runs = {WEEKLY: _runrow(WEEKLY, last_week_run)}
    r = _weekly_report(runs, monday, now)
    assert r.pg is True
    assert r.fired is True          # FRESH — no BUG2 false-positive
    assert r.pg_overdue is False
    assert r.pg_status == "ok"


def test_weekly_fresh_within_grace_even_before_row_lands():
    # Monday, AT the fire minute, row hasn't been written yet but we're inside the
    # grace deadline — still fresh (the run has time to land), not overdue.
    monday = dt.date(2026, 6, 15)
    now = dt.datetime(2026, 6, 15, 7, 22, tzinfo=dt.timezone.utc)  # 00:22 PT, post-fire
    last_week_run = dt.datetime(2026, 6, 8, 7, 9, tzinfo=dt.timezone.utc)
    runs = {WEEKLY: _runrow(WEEKLY, last_week_run)}
    r = _weekly_report(runs, monday, now)
    assert r.fired is True          # within fire+2h grace → not yet overdue
    assert r.pg_overdue is False


def test_weekly_fresh_when_this_weeks_run_landed():
    # The healthy steady state: this Monday's run has landed; stays green all week.
    wednesday = dt.date(2026, 6, 17)
    now = dt.datetime(2026, 6, 17, 7, 22, tzinfo=dt.timezone.utc)  # Wed, mid-week
    this_week_run = dt.datetime(2026, 6, 15, 7, 9, tzinfo=dt.timezone.utc)  # Mon 00:09 PT
    runs = {WEEKLY: _runrow(WEEKLY, this_week_run)}
    r = _weekly_report(runs, wednesday, now)
    assert r.fired is True
    assert r.pg_overdue is False


def test_weekly_overdue_on_genuine_miss():
    # A genuinely-missed weekly: it's Wednesday, well past Monday's fire+grace, and
    # the latest row is from a PRIOR week (this Monday never ran). MUST be overdue —
    # the schedule-aware check does NOT stay green for ~8 days off a stale run.
    wednesday = dt.date(2026, 6, 17)
    now = dt.datetime(2026, 6, 17, 7, 22, tzinfo=dt.timezone.utc)
    stale_run = dt.datetime(2026, 6, 8, 7, 9, tzinfo=dt.timezone.utc)  # last week's run
    runs = {WEEKLY: _runrow(WEEKLY, stale_run)}
    r = _weekly_report(runs, wednesday, now)
    assert r.fired is False
    assert r.pg_overdue is True
    assert r.fired_at_pt == "(2026-06-08)"  # shows the last real run's date


def test_weekly_overdue_right_after_fire_grace_with_no_fresh_row():
    # Monday, just AFTER fire+grace (00:08 + 2h = 02:08 PT), and no fresh row this
    # week — the run missed its window. Overdue (the per-week miss signal).
    monday = dt.date(2026, 6, 15)
    now = dt.datetime(2026, 6, 15, 9, 30, tzinfo=dt.timezone.utc)  # 02:30 PT, past grace
    stale_run = dt.datetime(2026, 6, 8, 7, 9, tzinfo=dt.timezone.utc)
    runs = {WEEKLY: _runrow(WEEKLY, stale_run)}
    r = _weekly_report(runs, monday, now)
    assert r.fired is False
    assert r.pg_overdue is True


def test_weekly_degraded_and_never_ran():
    monday = dt.date(2026, 6, 15)
    now = dt.datetime(2026, 6, 15, 7, 22, tzinfo=dt.timezone.utc)
    # PG unreachable → degraded
    degraded = _weekly_report(None, monday, now)
    assert degraded.pg_status == "degraded" and degraded.fired is False
    # No row ever → never
    never = _weekly_report({}, monday, now)
    assert never.fired is False and never.fired_at_pt is None and never.pg_status is None


# ─── artifact assertion: placeholder-in-note vs producer status (auto-review-byp) ─
#
# The OMG-002 defect (2026-06-18): the doctor reported agent-review 'ok' off the
# producer's ops.job_runs STATUS while the rendered note still carried the
# `_no agent-review report row for D_` placeholder. assess_agent_artifact asserts
# the ARTIFACT — but must NOT fire on a legitimate quiet day, which renders the
# IDENTICAL placeholder (producer ok, reports=0, no daily_reports row). The guard
# keys on "placeholder present AND producer persisted a report for D".

YDAY = dt.date(2026, 6, 18)


def _renderer_bracket(d: dt.date, inner: str) -> str:
    """Wrap `inner` in the REAL renderer begin/end bracket for date `d`
    (renderer/src/checkin_renderer/compose.py). The begin marker has NO
    generated_at; the end marker does. This is the ONLY structural anchor —
    the renderer strips legacy per-section `agent-review:report_date=` markers,
    so the fixtures contain none."""
    iso = d.isoformat()
    return (
        f"# check-in — {iso}\n\n"
        f"<!-- checkin-renderer:begin daily={iso} -->\n"
        f"{inner}\n"
        f"<!-- checkin-renderer:end daily={iso} generated_at=2026-06-19T08:17:09Z -->\n"
    )


def _note_with_agent_placeholder(d: dt.date = YDAY) -> str:
    # Quiet/placeholder agent-review section as the renderer writes it: the
    # heading AND placeholder are date-pinned to D (render_agent_section(None, D)).
    iso = d.isoformat()
    inner = (
        f"## agent-review — {iso}\n\n"
        f"_no agent-review report row for {iso}_"
    )
    return _renderer_bracket(d, inner)


def _note_with_real_agent_report(d: dt.date = YDAY) -> str:
    # A SUCCESSFUL agent-review section: the heading is keyed to the report's
    # generated-at (e.g. "## agent-review — 2026-06-19 00:17"), NOT to D, and
    # there is no placeholder string anywhere in the bracket.
    inner = (
        f"## agent-review — {d.isoformat()} 00:17\n\n"
        f"_window: {d.isoformat()} 00:00 → 00:17 · 3 sessions · 2 projects · ~$0.12_\n\n"
        f"### narrative\n\n"
        f"Shipped the artifact check and tidied the renderer bracket.\n\n"
        f"### stats\n\n"
        f"| sessions | est. cost |\n|---:|---:|\n| 3 | $0.1200 |"
    )
    return _renderer_bracket(d, inner)


def _ar_runrow(reports: int, dates, status="ok", finished=None):
    return doctor.RunRow(
        job_name="agent-review",
        finished_at=finished or dt.datetime(2026, 6, 19, 8, 10, tzinfo=dt.timezone.utc),
        status=status,
        cost_usd=0.12 if reports else None,
        summary={"reports": reports, "dates": dates, "sessions": 3 if reports else 0},
    )


def test_artifact_warns_when_placeholder_but_report_persisted():
    # (a) REGRESSION GUARD: renderer bracket present + the date-pinned placeholder
    # inside it AND the producer persisted a report for D (reports>=1, dates
    # includes D) → the real OMG-002 defect → WARN. This case FAILS against the
    # old marker-based extraction (it looked for a per-section
    # `agent-review:report_date=` marker the renderer never emits, so it always
    # returned None and the warning could never fire).
    runs = {"agent-review": _ar_runrow(reports=1, dates=[YDAY.isoformat()])}
    note = _note_with_agent_placeholder()
    assert "agent-review:report_date=" not in note  # renderer-shaped: no legacy marker
    assert "checkin-renderer:begin daily=" in note  # the real renderer bracket
    warn = doctor.assess_agent_artifact(note, YDAY, runs)
    assert warn is not None
    assert "artifact mismatch" in warn
    assert YDAY.isoformat() in warn


def test_artifact_quiet_day_stays_green():
    # (b) bracket present + placeholder + NO report (reports=0) + producer
    # status='ok' → a legitimate zero-session day renders the SAME string →
    # must stay silent (quiet day stays green).
    runs = {"agent-review": _ar_runrow(reports=0, dates=[YDAY.isoformat()], status="ok")}
    warn = doctor.assess_agent_artifact(_note_with_agent_placeholder(), YDAY, runs)
    assert warn is None


def test_artifact_no_warning_when_real_report_rendered():
    # (c) bracket present + a real agent-review narrative (no placeholder) →
    # nothing to flag, even though the producer persisted a report.
    runs = {"agent-review": _ar_runrow(reports=1, dates=[YDAY.isoformat()])}
    warn = doctor.assess_agent_artifact(_note_with_real_agent_report(), YDAY, runs)
    assert warn is None


def test_artifact_no_warning_when_no_renderer_bracket():
    # (d) no renderer bracket at all → no warning. The renderer didn't run (its
    # liveness is separately PG-monitored), so there is nothing to assert here —
    # even with the placeholder text present and a persisted report.
    runs = {"agent-review": _ar_runrow(reports=1, dates=[YDAY.isoformat()])}
    note = (
        f"# check-in — {YDAY.isoformat()}\n\n"
        f"## agent-review — {YDAY.isoformat()}\n\n"
        f"_no agent-review report row for {YDAY.isoformat()}_\n"
    )
    assert doctor.assess_agent_artifact(note, YDAY, runs) is None


def test_artifact_silent_when_pg_degraded():
    # PG unreachable (pg_runs is None): can't tell a defect from a quiet day, so
    # don't false-alarm — the placeholder alone is NOT enough to warn.
    warn = doctor.assess_agent_artifact(_note_with_agent_placeholder(), YDAY, None)
    assert warn is None


def test_artifact_silent_when_no_agent_review_row():
    # Producer never recorded a run → no report signal → stay silent.
    warn = doctor.assess_agent_artifact(_note_with_agent_placeholder(), YDAY, {})
    assert warn is None


def test_artifact_silent_when_run_covered_a_different_day():
    # A stale latest row whose summary.dates is some OTHER day must NOT be misread
    # as covering D, even with reports>=1 — guards against a stale-row false positive.
    other = (YDAY - dt.timedelta(days=2)).isoformat()
    runs = {"agent-review": _ar_runrow(reports=1, dates=[other])}
    warn = doctor.assess_agent_artifact(_note_with_agent_placeholder(), YDAY, runs)
    assert warn is None


def test_artifact_silent_when_no_agent_section_in_note():
    # A renderer bracket exists for D but holds no agent-review placeholder (e.g.
    # only the memex section rendered) → no placeholder match → silent. A missing
    # agent section is a different signal, not this artifact check's concern.
    runs = {"agent-review": _ar_runrow(reports=1, dates=[YDAY.isoformat()])}
    note = _renderer_bracket(
        YDAY,
        f"## memex — {YDAY.isoformat()} — inbox\n\n_no captures in window_",
    )
    assert doctor.assess_agent_artifact(note, YDAY, runs) is None


def test_artifact_silent_without_dates():
    # An older run-row whose summary has `reports` but no `dates` can't pin the
    # aggregate count to D, so we stay silent rather than risk a false positive
    # (auto-review-byp roborev fix: `reports` is a total, not a per-day signal).
    runs = {"agent-review": doctor.RunRow(
        job_name="agent-review",
        finished_at=dt.datetime(2026, 6, 19, 8, 10, tzinfo=dt.timezone.utc),
        status="ok", cost_usd=0.1, summary={"reports": 2},
    )}
    warn = doctor.assess_agent_artifact(_note_with_agent_placeholder(), YDAY, runs)
    assert warn is None


def test_artifact_silent_on_multidate_backfill_run():
    # roborev review (auto-review-byp): a multi-date backfill run (e.g. 06-18..06-19)
    # records ALL requested dates in summary.dates and only an AGGREGATE reports
    # count. If 06-18 persisted but D=06-19 was quiet, a plain `D in dates` test
    # would misread D as covered and false-warn D's CORRECT placeholder. The fix
    # asserts only on a single-date run covering exactly D, so this stays silent.
    runs = {"agent-review": _ar_runrow(
        reports=1, dates=[(YDAY - dt.timedelta(days=1)).isoformat(), YDAY.isoformat()],
    )}
    warn = doctor.assess_agent_artifact(_note_with_agent_placeholder(), YDAY, runs)
    assert warn is None


def test_rows_to_runmap_parses_summary_reports():
    # The liveness query now selects summary too (5th column); reports is parsed out.
    rows = [
        ["agent-review", "2026-06-19T08:10:00Z", "ok", "0.12",
         '{"reports": 1, "dates": ["2026-06-18"], "sessions": 3}'],
        ["memex-sync", "2026-06-19T08:05:00Z", "ok", "", ""],   # empty summary → {}
    ]
    m = doctor._rows_to_runmap(rows)
    assert m["agent-review"].summary["reports"] == 1
    assert m["agent-review"].summary["dates"] == ["2026-06-18"]
    assert m["memex-sync"].summary == {}


def test_rows_to_runmap_back_compat_four_columns():
    # A 4-column row (pre-byp query shape) still parses, with an empty summary.
    m = doctor._rows_to_runmap([["agent-review", "2026-06-19T08:10:00Z", "ok", "0.12"]])
    assert m["agent-review"].summary == {}
    assert m["agent-review"].status == "ok"


def test_sql_latest_runs_selects_summary():
    # The single liveness query is EXTENDED (no new round-trip) to carry summary.
    assert "summary" in doctor.SQL_LATEST_RUNS


def test_render_section_surfaces_agent_artifact_warning():
    today = dt.date(2026, 6, 19)
    runs = {"agent-review": _ar_runrow(reports=1, dates=[YDAY.isoformat()])}
    warn = doctor.assess_agent_artifact(_note_with_agent_placeholder(), YDAY, runs)
    reports = _pg_reports(runs, today)
    out = doctor.render_section(
        today, reports, [], 0,
        (today - dt.timedelta(days=1), []), warn,
    )
    assert "artifact mismatch" in out


def test_agent_placeholder_literal_matches_renderer_source():
    # Drift guard: the doctor duplicates the renderer's placeholder literal (it
    # can't import the renderer package — it's a standalone stdlib script). Assert
    # the doctor's prefix still appears verbatim in sections/agent.py, so a rename
    # there fails THIS test instead of silently disabling the artifact check.
    agent_src = (
        Path(__file__).resolve().parents[1]
        / "renderer" / "src" / "checkin_renderer" / "sections" / "agent.py"
    )
    text = agent_src.read_text(encoding="utf-8")
    assert doctor.AGENT_PLACEHOLDER_PREFIX in text, (
        "doctor.AGENT_PLACEHOLDER_PREFIX drifted from sections/agent.py — "
        "the artifact check would silently stop matching the rendered placeholder"
    )


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} passed")

