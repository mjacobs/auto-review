"""Tests for agent_review.artifacts."""

# ---------------------------------------------------------------------------
# Helpers for building fake tool_call dicts
# ---------------------------------------------------------------------------
import json

from agent_review.artifacts import extract_artifacts


def _bash(id: int, command: str, result: str | None = None) -> dict:
    return {
        "id": id,
        "session_id": "test-session",
        "tool_name": "Bash",
        "category": "Bash",
        "call_index": id,
        "tool_use_id": f"toolu_{id:04d}",
        "input_json": json.dumps({"command": command}),
        "result_content": result,
        "subagent_session_id": None,
        "message_ordinal": id,
    }


def _write(id: int, path: str) -> dict:
    return {
        "id": id,
        "session_id": "test-session",
        "tool_name": "Write",
        "category": "Write",
        "call_index": id,
        "tool_use_id": f"toolu_{id:04d}",
        "input_json": json.dumps({"path": path}),
        "result_content": None,
        "subagent_session_id": None,
        "message_ordinal": id,
    }


def _edit(id: int, path: str) -> dict:
    return {
        "id": id,
        "session_id": "test-session",
        "tool_name": "Edit",
        "category": "Edit",
        "call_index": id,
        "tool_use_id": f"toolu_{id:04d}",
        "input_json": json.dumps({"file_path": path}),
        "result_content": None,
        "subagent_session_id": None,
        "message_ordinal": id,
    }


def _empty_input(id: int, tool_name: str = "Bash", category: str = "Bash") -> dict:
    return {
        "id": id,
        "session_id": "test-session",
        "tool_name": tool_name,
        "category": category,
        "call_index": id,
        "tool_use_id": f"toolu_{id:04d}",
        "input_json": "",
        "result_content": None,
        "subagent_session_id": None,
        "message_ordinal": id,
    }


def _bad_json(id: int, tool_name: str = "Bash", category: str = "Bash") -> dict:
    return {
        "id": id,
        "session_id": "test-session",
        "tool_name": tool_name,
        "category": category,
        "call_index": id,
        "tool_use_id": f"toolu_{id:04d}",
        "input_json": "{not valid json",
        "result_content": None,
        "subagent_session_id": None,
        "message_ordinal": id,
    }


# ---------------------------------------------------------------------------
# Commits
# ---------------------------------------------------------------------------

class TestCommitExtraction:
    def test_inline_message(self):
        tc = _bash(
            1,
            'git commit -m "fix: handle empty sync metadata"',
            result="[main a1b2c3d] fix: handle empty sync metadata\n 1 file changed",
        )
        arts = extract_artifacts([tc])
        assert len(arts) == 1
        a = arts[0]
        assert a["kind"] == "commit"
        assert a["note"] == "fix: handle empty sync metadata"
        assert a["ref"] == "a1b2c3d"
        assert a["tool_call_id"] == 1

    def test_inline_message_no_result_sha(self):
        tc = _bash(1, 'git commit -m "chore: update deps"', result=None)
        arts = extract_artifacts([tc])
        assert len(arts) == 1
        assert arts[0]["ref"] == "(unknown)"
        assert arts[0]["note"] == "chore: update deps"

    def test_heredoc_commit_skips_coauthored(self):
        command = (
            "git commit -m \"$(cat <<'EOF'\n"
            "feat: add daily digest cache\n"
            "\n"
            "Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>\n"
            "EOF\n"
            ')"'
        )
        result_text = "[feature/cache abc1234] feat: add daily digest cache\n 3 files changed"
        tc = _bash(1, command, result=result_text)
        arts = extract_artifacts([tc])
        assert len(arts) == 1
        a = arts[0]
        assert a["note"] == "feat: add daily digest cache"
        assert a["ref"] == "abc1234"

    def test_heredoc_only_coauthored_lines_gives_no_subject(self):
        # Degenerate case: heredoc has only co-authored-by; subject becomes "(no message)"
        command = (
            "git commit -m \"$(cat <<'EOF'\n"
            "Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>\n"
            "EOF\n"
            ')"'
        )
        tc = _bash(1, command, result=None)
        arts = extract_artifacts([tc])
        assert len(arts) == 1
        assert arts[0]["note"] == "(no message)"

    def test_sha_extracted_from_branch_line(self):
        result_text = "[main deadbee] some commit message\n 5 files changed, 100 insertions(+)"
        tc = _bash(1, 'git commit -m "some commit message"', result=result_text)
        arts = extract_artifacts([tc])
        assert arts[0]["ref"] == "deadbee"


# ---------------------------------------------------------------------------
# Pushes
# ---------------------------------------------------------------------------

class TestPushExtraction:
    def test_push_with_dash_u(self):
        tc = _bash(1, "git push -u origin feature/foo")
        arts = extract_artifacts([tc])
        assert len(arts) == 1
        a = arts[0]
        assert a["kind"] == "branch_push"
        assert a["ref"] == "feature/foo"

    def test_push_simple(self):
        tc = _bash(1, "git push origin main")
        arts = extract_artifacts([tc])
        assert len(arts) == 1
        assert arts[0]["ref"] == "main"

    def test_push_help_skipped(self):
        tc = _bash(1, "git push --help")
        arts = extract_artifacts([tc])
        assert len(arts) == 0

    def test_push_dash_h_skipped(self):
        tc = _bash(1, "git push -h")
        arts = extract_artifacts([tc])
        assert len(arts) == 0


# ---------------------------------------------------------------------------
# PRs
# ---------------------------------------------------------------------------

class TestPrExtraction:
    def test_pr_with_url_in_result(self):
        tc = _bash(
            1,
            'gh pr create --title "Add daily digest cache" --body "Some body"',
            result="https://github.com/mjacobs/agent-review/pull/42\n",
        )
        arts = extract_artifacts([tc])
        assert len(arts) == 1
        a = arts[0]
        assert a["kind"] == "pr"
        assert a["note"] == "Add daily digest cache"
        assert a["ref"] == "https://github.com/mjacobs/agent-review/pull/42"

    def test_pr_no_url_in_result(self):
        tc = _bash(1, 'gh pr create --title "My PR" --body "body"', result=None)
        arts = extract_artifacts([tc])
        assert len(arts) == 1
        a = arts[0]
        assert a["note"] == "My PR"
        assert a["ref"] == "(pending)"

    def test_pr_no_title(self):
        tc = _bash(1, "gh pr create --base main", result=None)
        arts = extract_artifacts([tc])
        assert len(arts) == 1
        assert arts[0]["note"] == "(no title)"


# ---------------------------------------------------------------------------
# Tags
# ---------------------------------------------------------------------------

class TestTagExtraction:
    def test_annotated_tag(self):
        tc = _bash(1, "git tag -a v1.2.3 -m 'Release 1.2.3'")
        arts = extract_artifacts([tc])
        tag_arts = [a for a in arts if a["kind"] == "tag"]
        assert len(tag_arts) == 1
        assert tag_arts[0]["ref"] == "v1.2.3"

    def test_lightweight_tag(self):
        tc = _bash(1, "git tag v2.0.0")
        arts = extract_artifacts([tc])
        tag_arts = [a for a in arts if a["kind"] == "tag"]
        assert len(tag_arts) == 1
        assert tag_arts[0]["ref"] == "v2.0.0"


# ---------------------------------------------------------------------------
# Issues
# ---------------------------------------------------------------------------

class TestIssueExtraction:
    def test_issue_with_url(self):
        tc = _bash(
            1,
            'gh issue create --title "Bug: crash on startup" --body "details"',
            result="https://github.com/mjacobs/agent-review/issues/7\n",
        )
        arts = extract_artifacts([tc])
        issue_arts = [a for a in arts if a["kind"] == "issue"]
        assert len(issue_arts) == 1
        a = issue_arts[0]
        assert a["note"] == "Bug: crash on startup"
        assert a["ref"] == "https://github.com/mjacobs/agent-review/issues/7"


# ---------------------------------------------------------------------------
# File writes
# ---------------------------------------------------------------------------

class TestFileWriteExtraction:
    def test_write_tool_path_key(self):
        tc = _write(1, "/tmp/y.py")
        arts = extract_artifacts([tc])
        assert len(arts) == 1
        a = arts[0]
        assert a["kind"] == "file_write"
        assert a["ref"] == "/tmp/y.py"

    def test_write_tool_file_path_key(self):
        tc = {
            "id": 1,
            "session_id": "test-session",
            "tool_name": "Write",
            "category": "Write",
            "call_index": 1,
            "tool_use_id": "toolu_0001",
            "input_json": json.dumps({"file_path": "/home/user/out.txt"}),
            "result_content": None,
            "subagent_session_id": None,
            "message_ordinal": 1,
        }
        arts = extract_artifacts([tc])
        assert len(arts) == 1
        assert arts[0]["ref"] == "/home/user/out.txt"

    def test_lowercase_write_tool(self):
        tc = {
            **_write(1, "/tmp/z.py"),
            "tool_name": "write",
        }
        arts = extract_artifacts([tc])
        assert len(arts) == 1
        assert arts[0]["kind"] == "file_write"

    def test_apply_patch_path_from_unified_diff(self):
        patch_input = json.dumps({
            "patch": (
                "--- a/src/foo.py\n"
                "+++ b/src/foo.py\n"
                "@@ -1,3 +1,4 @@\n"
                " existing\n"
                "+new line\n"
            )
        })
        tc = {
            "id": 1,
            "session_id": "test-session",
            "tool_name": "apply_patch",
            "category": "Write",
            "call_index": 1,
            "tool_use_id": "toolu_0001",
            "input_json": patch_input,
            "result_content": None,
            "subagent_session_id": None,
            "message_ordinal": 1,
        }
        arts = extract_artifacts([tc])
        assert any(a["kind"] == "file_write" for a in arts)


# ---------------------------------------------------------------------------
# File edits
# ---------------------------------------------------------------------------

class TestFileEditExtraction:
    def test_edit_tool(self):
        tc = _edit(1, "/tmp/x.py")
        arts = extract_artifacts([tc])
        assert len(arts) == 1
        a = arts[0]
        assert a["kind"] == "file_edit"
        assert a["ref"] == "/tmp/x.py"
        assert a["tool_call_id"] == 1

    def test_lowercase_edit_tool(self):
        tc = {**_edit(1, "/src/main.py"), "tool_name": "edit"}
        arts = extract_artifacts([tc])
        assert len(arts) == 1
        assert arts[0]["kind"] == "file_edit"


# ---------------------------------------------------------------------------
# Robustness: empty / malformed input
# ---------------------------------------------------------------------------

class TestRobustness:
    def test_empty_input_json_no_crash(self):
        tc = _empty_input(1)
        arts = extract_artifacts([tc])
        # Bash tool with empty input → no artifacts (no command to parse)
        assert arts == []

    def test_malformed_json_no_crash(self):
        tc = _bad_json(1)
        arts = extract_artifacts([tc])
        assert arts == []

    def test_empty_tool_calls_list(self):
        assert extract_artifacts([]) == []

    def test_missing_keys_no_crash(self):
        # Minimal dict — should not raise even with missing keys
        tc = {"id": 1, "tool_name": "Bash", "category": "Bash", "input_json": ""}
        arts = extract_artifacts([tc])
        assert arts == []

    def test_empty_write_path_no_artifact(self):
        tc = {
            "id": 1,
            "session_id": "s",
            "tool_name": "Write",
            "category": "Write",
            "call_index": 1,
            "tool_use_id": "t",
            "input_json": json.dumps({}),  # no path key
            "result_content": None,
            "subagent_session_id": None,
            "message_ordinal": 1,
        }
        arts = extract_artifacts([tc])
        assert arts == []


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------

class TestDeduplication:
    def test_same_commit_deduped(self):
        cmd = 'git commit -m "fix: handle empty sync metadata"'
        result = "[main abc1234] fix: handle empty sync metadata"
        tc1 = _bash(1, cmd, result=result)
        tc2 = _bash(2, cmd, result=result)
        arts = extract_artifacts([tc1, tc2])
        commit_arts = [a for a in arts if a["kind"] == "commit"]
        # Same (kind, ref) → first wins
        assert len(commit_arts) == 1
        assert commit_arts[0]["tool_call_id"] == 1

    def test_same_file_edit_consecutive_deduped(self):
        tc1 = _edit(1, "/src/foo.py")
        tc2 = _edit(2, "/src/foo.py")
        arts = extract_artifacts([tc1, tc2])
        edit_arts = [a for a in arts if a["kind"] == "file_edit"]
        # Consecutive identical edits → drop second
        assert len(edit_arts) == 1

    def test_same_file_edit_non_consecutive_kept(self):
        tc1 = _edit(1, "/src/foo.py")
        tc2 = _edit(2, "/src/bar.py")  # different file in between
        tc3 = _edit(3, "/src/foo.py")
        arts = extract_artifacts([tc1, tc2, tc3])
        edit_arts = [a for a in arts if a["kind"] == "file_edit"]
        # Non-consecutive: both foo.py edits kept
        assert len(edit_arts) == 3

    def test_push_help_produces_no_artifact(self):
        tc = _bash(1, "git push --help")
        arts = extract_artifacts([tc])
        push_arts = [a for a in arts if a["kind"] == "branch_push"]
        assert len(push_arts) == 0

    def test_different_commits_not_deduped(self):
        tc1 = _bash(1, 'git commit -m "fix: one"', result="[main aaa1111] fix: one")
        tc2 = _bash(2, 'git commit -m "fix: two"', result="[main bbb2222] fix: two")
        arts = extract_artifacts([tc1, tc2])
        commit_arts = [a for a in arts if a["kind"] == "commit"]
        assert len(commit_arts) == 2


# ---------------------------------------------------------------------------
# Mixed session: commits + PRs + file ops
# ---------------------------------------------------------------------------

class TestMixedSession:
    def test_full_pipeline(self):
        tool_calls = [
            _edit(1, "/src/agent_review/artifacts.py"),
            _edit(2, "/tests/test_artifacts.py"),
            _bash(3, 'git commit -m "feat: add artifact extractor"',
                  result="[main d4e5f6a] feat: add artifact extractor\n 2 files changed"),
            _bash(4, "git push -u origin feat/artifact-extractor"),
            _bash(5, 'gh pr create --title "Add artifact extractor" --body "See design"',
                  result="https://github.com/mjacobs/agent-review/pull/99\n"),
        ]
        arts = extract_artifacts(tool_calls)
        kinds = {a["kind"] for a in arts}
        assert "commit" in kinds
        assert "branch_push" in kinds
        assert "pr" in kinds
        assert "file_edit" in kinds

        commit = next(a for a in arts if a["kind"] == "commit")
        assert commit["note"] == "feat: add artifact extractor"
        assert commit["ref"] == "d4e5f6a"

        pr = next(a for a in arts if a["kind"] == "pr")
        assert pr["ref"] == "https://github.com/mjacobs/agent-review/pull/99"
        assert pr["note"] == "Add artifact extractor"
