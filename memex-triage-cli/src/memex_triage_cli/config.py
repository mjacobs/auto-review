"""Process-wide config, populated from env / .env.

Trimmed from the sibling settings shape: the triage CLI never touches the D1
change feed, so it carries none of memex-sync's MEMEX_URL / CF Access creds —
just a Postgres DSN (for the `memex_triage` role) and a display timezone for
the inbox listing's HH:MM column.
"""

from __future__ import annotations

from zoneinfo import ZoneInfo

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Postgres DSN for the `memex_triage` role (password may come from ~/.pgpass
    # — see db.py). e.g. postgresql://memex_triage@<pg-host>:5432/<db>
    pg_dsn: SecretStr = Field(..., alias="MEMEX_TRIAGE_PG_DSN")

    # Display timezone for the inbox listing's HH:MM column (captures are stored
    # in UTC; this only affects rendering).
    tz_name: str = Field("America/Los_Angeles", alias="TZ")

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.tz_name)


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()  # type: ignore[call-arg]
    return _settings
