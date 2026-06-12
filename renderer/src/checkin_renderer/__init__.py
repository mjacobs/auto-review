"""checkin-renderer — the daily check-in note as a projection of Postgres rows.

One writer: reads the per-domain schemas (ops, memex, vault_review, projects,
agent_review) and emits journal/checkins/YYYY/MM/YYYY-MM-DD.md. See DESIGN.md.
"""

__version__ = "0.1.0"
