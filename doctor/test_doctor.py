"""Tests for auto-review-doctor v0.

The script ships as a single executable file with no .py extension, so load it
by path via importlib. Run with: `python3 -m pytest doctor/test_doctor.py` (or
`python3 doctor/test_doctor.py` for the lightweight asserts at the bottom).
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import sys
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
    # Sunday 2026-05-31 is in ISO week 2026-W22; the weekly cron runs
    # `last-week`, so the recap it writes covers 2026-W21.
    assert doctor.iso_week_label(dt.date(2026, 5, 31)) == "2026-W22"
    assert doctor.reported_week_label(dt.date(2026, 5, 31)) == "2026-W21"


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


# ─── assess_jobs: full weekly path on a Sunday ────────────────────────────────


def test_assess_jobs_weekly_present_on_sunday():
    sunday = dt.date(2026, 5, 31)
    log = ["[main deadbee] vault-review: weekly recap 2026-05-31T17:01:01Z\n"]
    reports = doctor.assess_jobs(log, sunday, yesterday_checkin_text="", weekly_text=WEEKLY_NOTE, tracebacks=[])
    weekly = next(r for r in reports if r.name == "vault-review weekly")
    assert weekly.skipped_reason is None  # Sunday → not skipped
    assert weekly.fired is True
    assert weekly.section_present is True
    assert weekly.section_lines >= 3


def test_assess_jobs_weekly_skipped_midweek():
    thursday = dt.date(2026, 5, 28)
    reports = doctor.assess_jobs([], thursday, yesterday_checkin_text="", weekly_text="", tracebacks=[])
    weekly = next(r for r in reports if r.name == "vault-review weekly")
    assert weekly.skipped_reason == "weekly — Sundays only"


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
        "  File \"/home/mj/.local/share/pipx/venvs/memex-review/lib/python3.10/site-packages/memex_review/client.py\", line 45, in get_thoughts\n",
        "    raise HTTPError(res.status_code, res.text)\n",
        "urllib.error.HTTPError: HTTP Error 500: Internal Server Error\n",
    ]
    tbs = doctor.find_tracebacks(log)
    reports = doctor.assess_jobs(log, dt.date(2026, 5, 31), "", "", tbs)
    memex = next(r for r in reports if r.name == "memex-review daily")
    assert memex.fired is False
    assert len(memex.tracebacks) == 1
    assert "HTTPError" in memex.tracebacks[0]


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} passed")
