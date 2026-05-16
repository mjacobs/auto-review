"""Process-wide config, populated from env / .env."""

from __future__ import annotations

from pathlib import Path
from zoneinfo import ZoneInfo

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    vault_path: Path = Field(Path.home() / "vault", alias="VAULT_PATH")
    tz_name: str = Field("America/Los_Angeles", alias="TZ")

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.tz_name)

    @property
    def checkins_dir(self) -> Path:
        return self.vault_path / "journal" / "checkins"

    @property
    def weekly_dir(self) -> Path:
        return self.vault_path / "journal" / "weekly"


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
