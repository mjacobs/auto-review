"""Module-level SQL constants for the triage surface.

Kept as named constants (not inline strings) so the test fake can dispatch on
identity — see tests/conftest.py. The grants the `memex_triage` role carries
(db/migrations/0005_roles.sql) are exactly: SELECT on memex.captures and
memex.capture_triage, plus UPDATE(state, updated_at) on memex.capture_triage.
There is deliberately NO INSERT/DELETE here — a triage flip always targets an
already-seeded row (the sync job seeds 'untriaged' per capture), so these two
statements are the whole vocabulary.
"""

from __future__ import annotations

# The inbox listing: captures joined to their triage row, filtered by state,
# ordered by the monotonic seq the human scans by.
SQL_INBOX = """
SELECT c.id, c.seq, c.content, c.summary, c.tags, c.created_at
FROM memex.captures c
JOIN memex.capture_triage t ON t.capture_id = c.id
WHERE t.state = %(state)s
ORDER BY c.seq
"""

# A single triage flip. UPDATE only — the row is guaranteed to exist (seeded by
# the sync job); the memex_triage role cannot INSERT here.
SQL_SET_STATE = """
UPDATE memex.capture_triage
SET state = %(state)s, updated_at = now()
WHERE capture_id = %(id)s
"""
