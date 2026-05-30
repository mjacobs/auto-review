"""Process-wide config, populated from env / .env."""

from __future__ import annotations

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

    pg_dsn: SecretStr = Field(..., alias="PG_DSN")
    llm_api_key: SecretStr = Field(..., alias="LLM_API_KEY")
    llm_base_url: str | None = Field(None, alias="LLM_BASE_URL")
    vault_path: Path = Field(Path.home() / "vault", alias="VAULT_PATH")
    tz_name: str = Field("America/Los_Angeles", alias="TZ")
    model_digest: str = Field("claude-haiku-4-5-20251001", alias="MODEL_DIGEST")
    model_synth: str = Field("claude-sonnet-4-6", alias="MODEL_SYNTH")
    # Schema name for the upstream read-only database (default: agentsview).
    pg_schema: str = Field("agentsview", alias="AGENT_REVIEW_PG_SCHEMA")

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.tz_name)

    @property
    def checkins_dir(self) -> Path:
        return self.vault_path / "journal" / "checkins"

    @property
    def daily_template(self) -> Path:
        return self.vault_path / "templates" / "daily.md"


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()  # type: ignore[call-arg]
    return _settings
