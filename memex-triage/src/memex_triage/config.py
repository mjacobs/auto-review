"""Process-wide config, populated from env / .env.

Mirrors the memex-review sibling's settings shape (same cf-memex creds, same
VAULT_PATH/TZ), and adds INBOX_PATH — the single rolling note that captures are
delivered into. The note also carries the delivery watermark in its frontmatter
(see inbox.py), so there is no separate state file.
"""

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

    vault_path: Path = Field(Path.home() / "vault", alias="VAULT_PATH")
    tz_name: str = Field("America/Los_Angeles", alias="TZ")
    # Inbox note, relative to the vault root (or absolute). The `inbox/` dir is
    # where other triage-bound content lands too.
    inbox_path: str = Field("inbox/memex.md", alias="INBOX_PATH")

    memex_url: str = Field(..., alias="MEMEX_URL")
    memex_client_id: SecretStr = Field(..., alias="MEMEX_CLIENT_ID")
    memex_client_secret: SecretStr = Field(..., alias="MEMEX_CLIENT_SECRET")

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.tz_name)

    @property
    def inbox_file(self) -> Path:
        p = Path(self.inbox_path).expanduser()
        return p if p.is_absolute() else self.vault_path / p


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
