"""
redaction.py — Pure-function regex-based secret scrubber.

Replaces likely secrets in text with «REDACTED:<kind>» markers before
text is sent to the Anthropic API.  The markers use guillemets so they
are visually distinct and almost impossible to appear in real text.

Rules (applied in order — most-specific first):
  1.  PEM private key blocks
  2.  AWS access key IDs
  3.  AWS secret access keys (when preceded by context keyword)
  4.  Anthropic API keys  (sk-ant-…)
  5.  OpenAI / generic sk- keys
  6.  GitHub fine-grained / OAuth tokens  (gh[pousr]_…)
  7.  Classic 40-hex GitHub tokens (only when preceded by context)
  8.  Slack tokens  (xox…)
  9.  Google API keys  (AIza…)
 10.  Bearer tokens in Authorization headers
 11.  .pgpass lines  (host:port:db:user:password)
 12.  Generic KEY=value / KEY: value / KEY="value" assignments
       where KEY matches a set of sensitive-sounding names

Ordering principle: specific patterns run before the generic KEY=value
sweep so that values already replaced by a specific rule are not
double-matched.  The generic pattern additionally skips values that
look like already-redacted markers.
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Marker
# ---------------------------------------------------------------------------

MARKER = "«REDACTED:{kind}»"


def _m(kind: str) -> str:
    return MARKER.format(kind=kind)


# Guillemet-marker prefix — used to detect already-redacted values so the
# generic pass doesn't re-process them.
_REDACTED_PREFIX = "«REDACTED:"

# ---------------------------------------------------------------------------
# 1. PEM private key blocks
#    Replaces the entire block (including headers) with one marker.
# ---------------------------------------------------------------------------

_PEM_BLOCK = re.compile(
    r"-----BEGIN [A-Z ]+PRIVATE KEY-----.*?-----END [A-Z ]+PRIVATE KEY-----",
    re.DOTALL,
)


def _redact_pem(text: str) -> str:
    return _PEM_BLOCK.sub(_m("private-key"), text)


# ---------------------------------------------------------------------------
# 2. AWS access key IDs
# ---------------------------------------------------------------------------

_AWS_ACCESS_KEY = re.compile(r"\bAKIA[0-9A-Z]{16}\b")


def _redact_aws_access_key(text: str) -> str:
    return _AWS_ACCESS_KEY.sub(_m("aws-access-key"), text)


# ---------------------------------------------------------------------------
# 3. AWS secret access keys (context-gated)
#    Matches lines/tokens like:
#      aws_secret_access_key = ABCDEF…
#      secret_key: ABCDEF…
#    The value pattern is relaxed to 38–44 chars (AWS uses 40, but some
#    tools truncate or pad slightly differently).
# ---------------------------------------------------------------------------

_AWS_SECRET_CTX = re.compile(
    r"""
    (?:aws_?secret_?access_?key | secret_?key | aws_secret)
    \s* [=:] \s*
    ([A-Za-z0-9+/]{38,44})
    """,
    re.IGNORECASE | re.VERBOSE,
)


def _redact_aws_secret(text: str) -> str:
    return _AWS_SECRET_CTX.sub(
        lambda m: m.group(0)[: m.start(1) - m.start(0)] + _m("aws-secret-key"),
        text,
    )


# ---------------------------------------------------------------------------
# 4. Anthropic API keys  sk-ant-…
# ---------------------------------------------------------------------------

_ANT_KEY = re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}")


def _redact_ant_key(text: str) -> str:
    return _ANT_KEY.sub(_m("anthropic-api-key"), text)


# ---------------------------------------------------------------------------
# 5. OpenAI / generic sk- keys (not already matched by Anthropic pattern)
# ---------------------------------------------------------------------------

_OPENAI_KEY = re.compile(r"\bsk-[A-Za-z0-9]{20,}")


def _redact_openai_key(text: str) -> str:
    return _OPENAI_KEY.sub(_m("api-key"), text)


# ---------------------------------------------------------------------------
# 6. GitHub fine-grained / OAuth / action tokens  gh[pousr]_…
#    These tokens are 40 chars total (prefix + 36 alnum), but we use 30+
#    to handle minor length variation across GitHub token types.
# ---------------------------------------------------------------------------

_GH_TOKEN = re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}")


def _redact_gh_token(text: str) -> str:
    return _GH_TOKEN.sub(_m("github-token"), text)


# ---------------------------------------------------------------------------
# 7. Classic 40-hex GitHub personal access tokens (context-gated)
#    Only match when preceded by github / gh_token / personal access token.
#    This avoids false-positives on git commit SHAs.
# ---------------------------------------------------------------------------

_GH_PAT_CTX = re.compile(
    r"""
    (?:github | gh_token | personal[ _]access[ _]token | GITHUB_TOKEN)
    \s* [=:\s] \s*
    ([a-f0-9]{40})
    \b
    """,
    re.IGNORECASE | re.VERBOSE,
)


def _redact_gh_pat(text: str) -> str:
    return _GH_PAT_CTX.sub(
        lambda m: m.group(0)[: m.start(1) - m.start(0)] + _m("github-token"),
        text,
    )


# ---------------------------------------------------------------------------
# 8. Slack tokens  xox[baprs]-…
# ---------------------------------------------------------------------------

_SLACK_TOKEN = re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}")


def _redact_slack(text: str) -> str:
    return _SLACK_TOKEN.sub(_m("slack-token"), text)


# ---------------------------------------------------------------------------
# 9. Google API keys  AIza…
#    Google API keys are exactly 39 chars: "AIza" + 35 base64url chars.
# ---------------------------------------------------------------------------

_GOOGLE_KEY = re.compile(r"\bAIza[0-9A-Za-z_-]{35}")


def _redact_google(text: str) -> str:
    return _GOOGLE_KEY.sub(_m("google-api-key"), text)


# ---------------------------------------------------------------------------
# 10. Bearer tokens in Authorization headers
#     Authorization: Bearer <token>
#     Must run BEFORE the generic pass so "Bearer" keyword isn't caught
#     as a generic assignment.
# ---------------------------------------------------------------------------

_BEARER = re.compile(
    r"(Authorization\s*:\s*Bearer\s+)([A-Za-z0-9\-._~+/]+=*)",
    re.IGNORECASE,
)


def _redact_bearer(text: str) -> str:
    return _BEARER.sub(lambda m: m.group(1) + _m("bearer-token"), text)


# ---------------------------------------------------------------------------
# 11. .pgpass lines  host:port:db:user:password
#     Five colon-separated fields; redact the password (5th) field.
# ---------------------------------------------------------------------------

_PGPASS = re.compile(
    r"""
    ^
    ([^:\n]+:[^:\n]+:[^:\n]+:[^:\n]+:)  # host:port:db:user:
    ([^\n]+)                              # password (to EOL)
    """,
    re.MULTILINE | re.VERBOSE,
)


def _redact_pgpass(text: str) -> str:
    def _pgpass_replace(m: re.Match) -> str:
        password = m.group(2)
        # Don't double-redact
        if password.startswith(_REDACTED_PREFIX):
            return m.group(0)
        return m.group(1) + _m("password")

    return _PGPASS.sub(_pgpass_replace, text)


# ---------------------------------------------------------------------------
# 12. Generic KEY=value / KEY: value / KEY="value" assignments
#
# Matches any assignment where the key contains a sensitive keyword.
# The value is replaced; already-redacted markers are skipped so this
# pass is safe to run after the specific passes above.
# ---------------------------------------------------------------------------

# Pattern for the sensitive key names — word-boundary anchored so that
# "mytoken" doesn't match "token", but "TOKEN", "API_KEY", "PASSWORD" do.
# We allow the key to be prefixed with arbitrary identifiers (e.g. GITHUB_TOKEN,
# MY_API_KEY) by matching word characters before the keyword.
_GENERIC_ASSIGN = re.compile(
    r"""
    (
      \b                              # word boundary before keyword
      (?:\w+_)?                       # optional prefix like GITHUB_, MY_, etc.
      (?:password|passwd|secret|api[_-]?key|token|auth(?:orization)?|bearer|
         private[_-]?key|credentials?)
      \s* [=:] \s*
    )
    (
      «REDACTED:[^»]+»                # already redacted — skip
      | " [^"\n]* "                   # double-quoted value
      | ' [^'\n]* '                   # single-quoted value
      | [^\s,;\n\]"'«]+               # unquoted value (stop at whitespace/guillemet)
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)


# HTTP scheme keywords that are not secrets themselves (appear after Authorization:)
_HTTP_SCHEME_WORDS = frozenset({"Bearer", "Basic", "Digest", "NTLM", "Negotiate", "OAuth"})


def _redact_generic(text: str) -> str:
    def _replace(m: re.Match) -> str:
        key_part = m.group(1)
        value = m.group(2)
        # Skip already-redacted values
        if value.startswith(_REDACTED_PREFIX):
            return m.group(0)
        # Skip HTTP scheme keywords (e.g. "Authorization: Bearer" — "Bearer" itself
        # is not a secret; the token after it is handled by _redact_bearer).
        if value in _HTTP_SCHEME_WORDS:
            return m.group(0)
        # Preserve outer quotes so the substitution looks syntactically valid.
        if value.startswith('"') and value.endswith('"'):
            return key_part + '"' + _m("password") + '"'
        if value.startswith("'") and value.endswith("'"):
            return key_part + "'" + _m("password") + "'"
        return key_part + _m("password")

    return _GENERIC_ASSIGN.sub(_replace, text)


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

_PIPELINE = [
    _redact_pem,
    _redact_aws_access_key,
    _redact_aws_secret,
    _redact_ant_key,
    _redact_openai_key,
    _redact_gh_token,
    _redact_gh_pat,
    _redact_slack,
    _redact_google,
    _redact_bearer,
    _redact_pgpass,
    _redact_generic,
]


def redact(text: str) -> str:
    """Return *text* with likely secrets replaced by «REDACTED:<kind>» markers.

    The function is idempotent: redact(redact(x)) == redact(x).
    """
    if not text:
        return text
    for fn in _PIPELINE:
        text = fn(text)
    return text
