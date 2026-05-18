"""Cursor state for linear-consumption inbox processing.

The cursor is a single tz-aware datetime stored in the vault at
``vault/state/memex-review.yaml``. Everything captured at or after the
cursor is "inbox"; everything before is "processed" (whatever the user
did with it — wrote into a project note, ignored, or backlog-dumped).

The cursor only advances via an explicit save (`memex-review process`
or `cursor --init`); a load against a missing file returns the
bootstrap default but does not persist it.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import os
import tempfile
from pathlib import Path

import yaml

from .client import Thought
from .config import Settings


def cursor_path(settings: Settings) -> Path:
    return settings.vault_path / "state" / "memex-review.yaml"


def _bootstrap_default(settings: Settings) -> dt.datetime:
    today = dt.datetime.now(tz=settings.tz).date()
    return dt.datetime(today.year, today.month, today.day, tzinfo=settings.tz)


def load_cursor(settings: Settings) -> dt.datetime:
    """Return the current cursor, or the bootstrap default if no file exists.

    Does NOT write the bootstrap default — only an explicit `save_cursor`
    persists.
    """
    path = cursor_path(settings)
    if not path.exists():
        return _bootstrap_default(settings)

    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict) or "cursor" not in data:
        raise ValueError(f"Cursor file {path} is missing the 'cursor' key")

    raw = data["cursor"]
    if isinstance(raw, dt.datetime):
        value = raw
    elif isinstance(raw, str):
        try:
            value = dt.datetime.fromisoformat(raw)
        except ValueError as e:
            raise ValueError(f"Cursor file {path} has unparseable cursor: {raw!r}") from e
    else:
        raise ValueError(f"Cursor file {path} has unexpected cursor type: {type(raw).__name__}")

    if value.tzinfo is None:
        raise ValueError(f"Cursor file {path} has naive datetime; tz required")
    return value.astimezone(settings.tz)


def save_cursor(settings: Settings, value: dt.datetime) -> None:
    """Atomically write the cursor, preserving any future extension keys."""
    if value.tzinfo is None:
        raise ValueError("save_cursor requires a tz-aware datetime")

    path = cursor_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)

    existing: dict = {}
    if path.exists():
        with path.open("r", encoding="utf-8") as f:
            loaded = yaml.safe_load(f)
        if isinstance(loaded, dict):
            existing = loaded

    existing["cursor"] = value.isoformat()

    fd, tmp_name = tempfile.mkstemp(
        prefix=".memex-review.yaml.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            yaml.safe_dump(existing, f, sort_keys=False, default_flow_style=False)
        os.replace(tmp_name, path)
    except Exception:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp_name)
        raise


def filter_visible(thoughts: list[Thought], cursor: dt.datetime) -> list[Thought]:
    """Drop thoughts captured before the cursor; keep `created_at >= cursor`."""
    if cursor.tzinfo is None:
        raise ValueError("filter_visible requires a tz-aware cursor")
    return [t for t in thoughts if t.created_at >= cursor]
