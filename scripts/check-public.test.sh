#!/usr/bin/env bash
# check-public.test.sh — regression test for scripts/check-public.sh
# (auto-review-6mf.4; roborev job 1307 asked for coverage of the guard logic).
#
# Builds a throwaway git repo, drops the guard in, and asserts it:
#   1) passes on a clean tree,
#   2) fails on a planted leak — plain IP, an IP preceded by a word char (the
#      \b-anchor gap the guard was fixed for), the deploy hostname, a home path,
#   3) passes once the leak is allowlisted (whole-file and line-scoped),
#   4) never scans *.example* files.
# Exits nonzero on the first failed assertion.
set -euo pipefail

guard="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/check-public.sh"
[[ -f "$guard" ]] || { echo "cannot find guard at $guard" >&2; exit 2; }

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
cd "$tmp"

git init -q
git config user.email test@example.com
git config user.name test
mkdir -p scripts
cp "$guard" scripts/check-public.sh
: > scripts/check-public.allow
echo "a clean mechanism doc, no instance values here" > README.md
git add -A && git commit -qm init

# The guard exits 0 (clean) or 1 (leak found).
guard_clean() { bash scripts/check-public.sh >/dev/null 2>&1; }
commit_all()  { git add -A && git commit -qm "$1"; }

assert_pass() {  # guard should find nothing
  if guard_clean; then echo "ok:   $1"; else echo "FAIL (expected clean): $1" >&2; exit 1; fi
}
assert_fail() {  # guard should find a leak
  if guard_clean; then echo "FAIL (expected leak): $1" >&2; exit 1; else echo "ok:   $1 (leak caught)"; fi
}

assert_pass "clean tree"

printf 'connect to 192.168.5.42\n' > leak.txt;        commit_all l1
assert_fail "plain RFC1918 IP"

# IP preceded by a word char (e.g. an escape in a string literal). A leading \b
# anchor missed this; (^|[^0-9.]) catches it. This is the core of the fix.
printf 'msg = "boom\\n10.0.0.9 down"\n' > leak.txt;    commit_all l2
assert_fail "IP preceded by a word char (\\b-anchor gap)"

printf 'ssh deploy@auto-review-lxc\n' > leak.txt;      commit_all l3
assert_fail "deploy hostname auto-review-lxc"

printf 'path: /home/mj/secret\n' > leak.txt;           commit_all l4
assert_fail "operator home path /home/mj"

# Whole-file allowlist entry suppresses the file entirely.
echo "leak.txt" > scripts/check-public.allow;          commit_all allow-file
assert_pass "leak suppressed by whole-file allowlist"

# Line-scoped allowlist entry suppresses only matching lines.
printf '10.0.0.9\n' > leak.txt
printf 'leak.txt:10\\.0\\.0\\.9\n' > scripts/check-public.allow; commit_all allow-line
assert_pass "leak suppressed by line-scoped allowlist"

# *.example* files are never scanned. Drop the earlier leak fixture and clear
# the allowlist so db.env.example is the only file carrying a leak pattern.
git rm -q leak.txt
: > scripts/check-public.allow
printf 'connect to 192.168.5.42\n' > db.env.example;   commit_all example
assert_pass "*.example* file excluded from scan"

echo "ALL check-public.test.sh assertions passed"
