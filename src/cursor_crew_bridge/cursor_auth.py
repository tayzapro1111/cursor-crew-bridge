"""Read this machine's Cursor IDE session. Never print or log the token."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

AUTH_DB = Path.home() / "AppData" / "Roaming" / "Cursor" / "User" / "globalStorage" / "state.vscdb"
ACCESS_KEY = "cursorAuth/accessToken"
EMAIL_KEY = "cursorAuth/cachedEmail"
REFRESH_KEY = "cursorAuth/refreshToken"


def auth_db_candidates() -> list[Path]:
    """Windows first (existing path), then macOS / Linux Cursor stores."""

    home = Path.home()
    override = os.environ.get("CURSOR_AUTH_DB", "").strip()
    found: list[Path] = []
    if override:
        found.append(Path(override))
    found.extend(
        [
            AUTH_DB,
            home
            / "Library"
            / "Application Support"
            / "Cursor"
            / "User"
            / "globalStorage"
            / "state.vscdb",
            home / ".config" / "Cursor" / "User" / "globalStorage" / "state.vscdb",
        ]
    )
    seen: set[str] = set()
    unique: list[Path] = []
    for path in found:
        key = os.path.normcase(str(path))
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


def _read_item(key: str) -> str:
    for db in auth_db_candidates():
        value = _read_item_from(db, key)
        if value:
            return value
    return ""


def _read_item_from(db: Path, key: str) -> str:
    if not db.is_file():
        return ""
    uri = db.resolve().as_posix()
    try:
        con = sqlite3.connect(f"file:{uri}?mode=ro", uri=True, timeout=5)
    except sqlite3.Error:
        return ""
    try:
        row = con.execute("SELECT value FROM ItemTable WHERE key = ?", (key,)).fetchone()
    except sqlite3.Error:
        return ""
    finally:
        con.close()
    if not row:
        return ""
    value = row[0]
    if isinstance(value, bytes):
        value = value.decode("utf-8", "replace")
    if not isinstance(value, str):
        return ""
    text = value.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {'"', "'"}:
        try:
            import json

            decoded = json.loads(text)
            if isinstance(decoded, str):
                return decoded.strip()
        except ValueError:
            text = text.strip('"').strip("'")
    return text


def cached_email() -> str:
    return _read_item(EMAIL_KEY)


def access_token() -> str:
    override = os.environ.get("CURSOR_AUTH_TOKEN", "").strip()
    if override:
        return override
    return _read_item(ACCESS_KEY)


def child_env(base: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(base if base is not None else os.environ)
    token = access_token()
    if token and not env.get("CURSOR_AUTH_TOKEN", "").strip():
        env["CURSOR_AUTH_TOKEN"] = token
    return env
