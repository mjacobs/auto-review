"""Process-wide config, populated from env / .env."""

from __future__ import annotations

import datetime as dt
import socket
from pathlib import Path
from zoneinfo import ZoneInfo

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    vault_path: Path = Field(Path.home() / "vault", alias="VAULT_PATH")
    tz_name: str = Field("America/Los_Angeles", alias="TZ")

    # Postgres DSN for the `vault_review_job` role (password may come from
    # ~/.pgpass — see db.py). e.g. postgresql://vault_review_job@<pg-host>:5432/<db>
    # OPTIONAL: vault-review's core job is a pure git-diff vault write; the DSN is
    # only needed to record ops.job_runs liveness (auto-review-2vv). When unset
    # (e.g. tests, a box without PG) the run still writes its section and just
    # records no row — db.connect() raises a clear error if reached. Role-scoped
    # var because the cron host's plain PG_DSN belongs to agent_review.
    pg_dsn: SecretStr | None = Field(None, alias="VAULT_REVIEW_PG_DSN")

    # ops.job_runs identity. One CLI process serves both jobs; the daily/weekly
    # run paths pass the matching name. Each must match a pre-registered ops.jobs
    # row (the FK is intentional — see db/README.md); seeded by 0008.
    daily_job_name: str = Field("vault-review-daily", alias="VAULT_REVIEW_DAILY_JOB_NAME")
    weekly_job_name: str = Field("vault-review-weekly", alias="VAULT_REVIEW_WEEKLY_JOB_NAME")
    job_host: str = Field("", alias="VAULT_REVIEW_HOST")

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.tz_name)

    @property
    def host(self) -> str:
        return self.job_host or socket.gethostname()

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
        return self.vault_path / "journal" / "weekly"


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
