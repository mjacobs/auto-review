"""Tests for vault_review.gitdelta — collect_events against a real git repo."""

from __future__ import annotations

import datetime as dt
import subprocess
from pathlib import Path

import pytest

from vault_review.gitdelta import collect_events


# ─── fixtures ────────────────────────────────────────────────────────────────


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


@pytest.fixture()
def vault_repo(tmp_path: Path) -> Path:
    """A minimal git repo that mimics the vault directory layout.

    Commits:
      T-2 days: add journal/checkins/2026-05-12.md
      T-1 days: add journal/checkins/2026-05-13.md, modify projects/foo/bar.md
      T+0 days: add journal/checkins/2026-05-14.md, add .obsidian/workspace (denied)
    """
    repo = tmp_path / "vault"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")

    def commit(rel: str, content: str, when: str, mode: str = "A"):
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        _git(repo, "add", rel)
        env_patch = f"GIT_AUTHOR_DATE={when} GIT_COMMITTER_DATE={when}"
        subprocess.run(
            f'cd {repo} && {env_patch} git commit -m "add {rel}"',
            shell=True,
            check=True,
        )

    # Day 1: 2026-05-12
    commit("journal/checkins/2026-05-12.md", "# check-in\n", "2026-05-12T10:00:00")
    # Day 2: 2026-05-13
    commit("journal/checkins/2026-05-13.md", "# check-in\n", "2026-05-13T10:00:00")
    commit("projects/foo/bar.md", "# foo bar\n", "2026-05-13T11:00:00")
    # Day 3: 2026-05-14 — includes a denylisted path
    commit("journal/checkins/2026-05-14.md", "# check-in\n", "2026-05-14T10:00:00")
    (repo / ".obsidian").mkdir(exist_ok=True)
    (repo / ".obsidian" / "workspace").write_text("{}", encoding="utf-8")
    _git(repo, "add", ".obsidian/workspace")
    subprocess.run(
        f'cd {repo} && GIT_AUTHOR_DATE=2026-05-14T10:00:00 GIT_COMMITTER_DATE=2026-05-14T10:00:00 git commit -m "obsidian workspace"',
        shell=True,
        check=True,
    )

    return repo


# ─── tests ───────────────────────────────────────────────────────────────────


class TestCollectEvents:
    def test_returns_events_for_single_day(self, vault_repo):
        start = dt.datetime(2026, 5, 13, 0, 0, 0)
        end = dt.datetime(2026, 5, 13, 23, 59, 59)
        events = collect_events(vault_repo, start, end)
        paths = [p2 or p1 for _, p1, p2 in events]
        assert "journal/checkins/2026-05-13.md" in paths
        assert "projects/foo/bar.md" in paths

    def test_excludes_denylisted_paths(self, vault_repo):
        start = dt.datetime(2026, 5, 14, 0, 0, 0)
        end = dt.datetime(2026, 5, 14, 23, 59, 59)
        events = collect_events(vault_repo, start, end)
        paths = [p2 or p1 for _, p1, p2 in events]
        assert not any(".obsidian" in p for p in paths)

    def test_only_md_files_included(self, vault_repo):
        start = dt.datetime(2026, 5, 13, 0, 0, 0)
        end = dt.datetime(2026, 5, 14, 23, 59, 59)
        events = collect_events(vault_repo, start, end)
        for _, p1, p2 in events:
            effective = p2 or p1
            assert effective.endswith(".md"), f"non-.md path leaked: {effective}"

    def test_empty_window_returns_empty_list(self, vault_repo):
        # Window before any commits
        start = dt.datetime(2026, 5, 1, 0, 0, 0)
        end = dt.datetime(2026, 5, 1, 23, 59, 59)
        events = collect_events(vault_repo, start, end)
        assert events == []

    def test_week_window_covers_multiple_days(self, vault_repo):
        start = dt.datetime(2026, 5, 12, 0, 0, 0)
        end = dt.datetime(2026, 5, 14, 23, 59, 59)
        events = collect_events(vault_repo, start, end)
        paths = {p2 or p1 for _, p1, p2 in events}
        assert "journal/checkins/2026-05-12.md" in paths
        assert "journal/checkins/2026-05-13.md" in paths
        assert "journal/checkins/2026-05-14.md" in paths

    def test_deduplication(self, vault_repo):
        """Same (status, path1, path2) tuple should appear only once."""
        start = dt.datetime(2026, 5, 12, 0, 0, 0)
        end = dt.datetime(2026, 5, 14, 23, 59, 59)
        events = collect_events(vault_repo, start, end)
        seen: set[tuple] = set()
        for ev in events:
            assert ev not in seen, f"duplicate event: {ev}"
            seen.add(ev)

    def test_status_codes_present(self, vault_repo):
        start = dt.datetime(2026, 5, 12, 0, 0, 0)
        end = dt.datetime(2026, 5, 14, 23, 59, 59)
        events = collect_events(vault_repo, start, end)
        statuses = {s for s, _, _ in events}
        assert "A" in statuses  # adds present

    def test_bad_repo_raises_runtime_error(self, tmp_path):
        not_a_repo = tmp_path / "notarepo"
        not_a_repo.mkdir()
        with pytest.raises(RuntimeError, match="git log failed"):
            collect_events(not_a_repo, dt.datetime(2026, 5, 1), dt.datetime(2026, 5, 2))
