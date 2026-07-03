#!/usr/bin/env bash
# check-public.sh — regression guard for the infra/content separation policy
# (auto-review-6mf.4).
#
# This repo is PUBLIC. Instance values — real hosts, IPs, schedules, and
# filesystem paths — must live in PG/vault/gitignored-seed, never in tracked
# files; the repo holds mechanism only. See:
#   docs/superpowers/specs/2026-06-27-infra-content-separation-design.md
#
# This script greps TRACKED files for known leak shapes and exits nonzero on
# any un-allowlisted hit. Known, justified exceptions (pending structural
# cleanup) live in scripts/check-public.allow — see that file for details.
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"

spec_doc="docs/superpowers/specs/2026-06-27-infra-content-separation-design.md"
allow_file="scripts/check-public.allow"

# ---------------------------------------------------------------------------
# LEAK PATTERNS — regex@@human-readable reason. A hit against any regex here
# is a content leak per the design doc's classification rule: "if removing
# this line would only matter to this one operator's machines, it is content
# and does not belong in the repo." Extend this array as new instance-value
# shapes are discovered; keep each entry's reason short (it's printed on
# failure).
#
# NOTE: America/Los_Angeles / TZ is NOT a leak — it's the accepted code
# default (config.py hardcodes it) and is intentionally not matched here.
# ---------------------------------------------------------------------------
declare -a LEAK_PATTERNS=(
  # 1. Full RFC1918 IPv4 addresses. Anchored with (^|[^0-9.]) rather than a
  #    leading \b: \b matches only between a word and non-word char, so an IP
  #    preceded by a word char (e.g. the "n" in a "…\n192.168.1.1" string
  #    literal) is NOT at a \b and would slip through. [^0-9.] instead admits
  #    that case while still not matching mid-address (roborev job 1307).
  '(^|[^0-9.])10\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\b@@real RFC1918 IPv4 (10.x.x.x)'
  '(^|[^0-9.])192\.168\.[0-9]{1,3}\.[0-9]{1,3}\b@@real RFC1918 IPv4 (192.168.x.x)'
  '(^|[^0-9.])172\.(1[6-9]|2[0-9]|3[01])\.[0-9]{1,3}\.[0-9]{1,3}\b@@real RFC1918 IPv4 (172.16-31.x.x)'
  # 2. Homelab host octet-shorthands (the real last-octet shorthands the docs use).
  '\.223\b@@homelab host octet-shorthand (.223)'
  '\.199\b@@homelab host octet-shorthand (.199)'
  '\.7\.5\b@@homelab host octet-shorthand (.7.5)'
  # 3. Real homelab hostnames (incl. the deploy host's DNS-style name, which
  #    the 0007-0009 seed-row INSERTs still carry until auto-review-6mf.2 lands).
  '\bbaox\b@@real homelab hostname (baox)'
  '\bopenclaw\b@@real homelab hostname (openclaw)'
  '\bportainer\b@@real homelab hostname (portainer)'
  '\bauto-review-lxc\b@@real deploy hostname (auto-review-lxc)'
  # 4. The operator's real home path (synthetic /home/user, /home/<user>,
  #    /home/<home>, /home/linuxbrew are shared placeholders and must NOT
  #    match this — the \b after "mj" already excludes /home/mjacobs etc.).
  '/home/mj\b@@operator real home path (/home/mj)'
)

# ---------------------------------------------------------------------------
# EXCLUSIONS — glob patterns (matched against the path as returned by
# `git ls-files`) that are never scanned: sanitized examples, an already-
# scrubbed reference snapshot, local issue-tracker state, git internals, and
# this guard's own files.
# ---------------------------------------------------------------------------
declare -a EXCLUDE_GLOBS=(
  '*.example*'
  'db/reference/*'
  '.beads/*'
  '.git/*'
  'scripts/check-public.sh'
  'scripts/check-public.allow'
  'scripts/check-public.test.sh'   # the guard's own test — contains fixture leaks
)

is_excluded() {
  local f="$1" glob
  for glob in "${EXCLUDE_GLOBS[@]}"; do
    # shellcheck disable=SC2053  # RHS is an intentional glob pattern, not a literal
    [[ "$f" == $glob ]] && return 0
  done
  return 1
}

# Load the allowlist into two parallel arrays: ALLOW_PATH[i] / ALLOW_REGEX[i]
# (ALLOW_REGEX[i] is empty for a whole-file entry).
declare -a ALLOW_PATH=()
declare -a ALLOW_REGEX=()
if [[ -f "$allow_file" ]]; then
  while IFS= read -r raw_line || [[ -n "$raw_line" ]]; do
    stripped="${raw_line%%#*}"                # strip trailing comments
    stripped="$(printf '%s' "$stripped" | sed -E 's/^[[:space:]]+|[[:space:]]+$//g')"
    [[ -z "$stripped" ]] && continue
    if [[ "$stripped" == *:* ]]; then
      ALLOW_PATH+=("${stripped%%:*}")
      ALLOW_REGEX+=("${stripped#*:}")
    else
      ALLOW_PATH+=("$stripped")
      ALLOW_REGEX+=("")
    fi
  done < "$allow_file"
fi

is_allowed() {
  local file="$1" content="$2" i
  for i in "${!ALLOW_PATH[@]}"; do
    [[ "$file" != "${ALLOW_PATH[$i]}" ]] && continue
    if [[ -z "${ALLOW_REGEX[$i]}" ]]; then
      return 0                                   # whole-file exception
    fi
    if grep -qE -- "${ALLOW_REGEX[$i]}" <<< "$content"; then
      return 0                                   # line-scoped exception
    fi
  done
  return 1
}

# Build the list of tracked, non-excluded files to scan.
declare -a scan_files=()
while IFS= read -r -d '' f; do
  is_excluded "$f" && continue
  scan_files+=("$f")
done < <(git ls-files -z)

fail=0
for entry in "${LEAK_PATTERNS[@]}"; do
  regex="${entry%%@@*}"
  reason="${entry#*@@}"
  [[ ${#scan_files[@]} -eq 0 ]] && continue
  while IFS=: read -r file line content; do
    [[ -z "$file" ]] && continue
    is_allowed "$file" "$content" && continue
    printf '%s:%s: %s\n' "$file" "$line" "$reason"
    printf '  -> see %s\n' "$spec_doc"
    fail=1
  # Batch files through xargs so a large tree can't exceed ARG_MAX and make grep
  # error out: with stderr hidden that would silently yield no matches and fail
  # the guard OPEN. xargs splits into as many grep calls as needed; -H keeps
  # every line prefixed file:line so the parse below is unchanged (roborev 1316).
  done < <(printf '%s\0' "${scan_files[@]}" | xargs -0 -r grep -nHE -- "$regex" 2>/dev/null)
done

if [[ "$fail" -ne 0 ]]; then
  echo "check-public: FAILED — internal content leaked into tracked files (see above)." >&2
  exit 1
fi

echo "check-public: OK — no internal content found in tracked files."
