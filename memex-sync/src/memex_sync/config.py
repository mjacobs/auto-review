"""Process-wide config, populated from env / .env.

Mirrors the sibling settings shape (same cf-memex creds as memex-triage /
memex-review; same PG_DSN convention as agent-review). No VAULT_PATH: this
tool touches no files — it reads the change feed and writes Postgres rows.
"""

from __future__ import annotations

import socket

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Postgres DSN for the `memex_sync` role (password may come from ~/.pgpass
    # — see db.py). e.g. postgresql://memex_sync@<pg-host>:5432/<db>
    pg_dsn: SecretStr = Field(..., alias="PG_DSN")

    # cf-memex change feed (same CF Access service-token creds as the siblings).
    memex_url: str = Field(..., alias="MEMEX_URL")
    memex_client_id: SecretStr = Field(..., alias="MEMEX_CLIENT_ID")
    memex_client_secret: SecretStr = Field(..., alias="MEMEX_CLIENT_SECRET")

    # Watermark key in memex.sync_state. The desktop memex-triage timer is an
    # independent consumer of the same feed with its own watermark (in its
    # inbox note's frontmatter); this name only has to be unique among
    # sync_state rows.
    consumer: str = Field("memex_sync", alias="MEMEX_SYNC_CONSUMER")

    # ops.job_runs identity. job_name must match a pre-registered ops.jobs row
    # (the FK is intentional — see db/README.md).
    job_name: str = Field("memex-sync", alias="MEMEX_SYNC_JOB_NAME")
    job_host: str = Field("", alias="MEMEX_SYNC_HOST")

    @property
    def host(self) -> str:
        return self.job_host or socket.gethostname()


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()  # type: ignore[call-arg]
    return _settings
