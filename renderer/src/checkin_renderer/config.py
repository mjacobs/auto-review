"""Process-wide config, populated from env / .env.

Mirrors the sibling settings shape (vault-review/agent-review). The DSN var is
role-scoped (CHECKIN_RENDERER_PG_DSN, memex-sync precedent) because the cron
host's plain PG_DSN belongs to agent_review.
"""

from __future__ import annotations

import datetime as dt
import socket
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Postgres DSN for the `checkin_renderer` role (password may come from
    # ~/.pgpass — see db.py). e.g. postgresql://checkin_renderer@<pg-host>:5432/<db>
    pg_dsn: SecretStr = Field(..., alias="CHECKIN_RENDERER_PG_DSN")

    vault_path: Path = Field(Path.home() / "vault", alias="VAULT_PATH")
    tz_name: str = Field("America/Los_Angeles", alias="TZ")

    # bracket: strip-and-replace the renderer's own begin/end pair, coexisting
    # with the remaining marker writers (transition mode — the default).
    # full:    whole-file regeneration; the step-D flip (DESIGN.md decision 2).
    #          Gated/announced — not active in Phase 1.
    render_mode: Literal["bracket", "full"] = Field("bracket", alias="RENDER_MODE")

    # ops.job_runs identity. job_name must match a pre-registered ops.jobs row
    # (the FK is intentional — see db/README.md); seeded at Phase 2 deploy.
    job_name: str = Field("checkin-renderer-daily", alias="CHECKIN_RENDERER_JOB_NAME")
    job_host: str = Field("", alias="CHECKIN_RENDERER_HOST")

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.tz_name)

    @property
    def host(self) -> str:
        return self.job_host or socket.gethostname()

    # ─── note-path helpers (shared shape with the siblings) ───────────────────

    @property
    def checkins_dir(self) -> Path:
        return self.vault_path / "journal" / "checkins"

    def checkin_path(self, date: dt.date) -> Path:
        """Path to a daily check-in note, nested by month.

        Layout: journal/checkins/YYYY/MM/YYYY-MM-DD.md (auto-review-d4c). The
        filename keeps the full date so markers/links/date-keys are unchanged —
        only the directory nests.
        """
        return self.checkins_dir / f"{date:%Y}" / f"{date:%m}" / f"{date.isoformat()}.md"

    @property
    def weekly_dir(self) -> Path:
        """journal/weekly/ — run-weekly target (Phase 3, DESIGN.md decision 6)."""
        return self.vault_path / "journal" / "weekly"

    @property
    def monthly_dir(self) -> Path:
        """journal/monthly/ — run-monthly target (Phase 4, auto-review-2l1)."""
        return self.vault_path / "journal" / "monthly"


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()  # type: ignore[call-arg]
    return _settings
