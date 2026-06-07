"""Process-wide config, populated from env / .env."""

from __future__ import annotations

import datetime as dt
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

    memex_url: str = Field(..., alias="MEMEX_URL")
    memex_client_id: SecretStr = Field(..., alias="MEMEX_CLIENT_ID")
    memex_client_secret: SecretStr = Field(..., alias="MEMEX_CLIENT_SECRET")

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.tz_name)

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


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
