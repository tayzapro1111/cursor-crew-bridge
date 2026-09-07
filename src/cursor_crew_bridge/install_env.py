"""Install the launcher into Kiro Crew's process environment."""

from __future__ import annotations

import os
from pathlib import Path

from cursor_crew_bridge.config import PROJECT_DIR, crew_env_path

KEY = "KIROCREW_KIRO_BIN"


def upsert_env_values(updates: dict[str, str], *, path: Path | None = None) -> Path:
    target = path or crew_env_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    remaining = dict(updates)
    if target.is_file():
        for line in target.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            replaced = False
            for key, value in list(remaining.items()):
                if stripped.startswith(f"{key}="):
                    lines.append(f"{key}={value}")
                    remaining.pop(key)
                    replaced = True
                    break
            if not replaced:
                lines.append(line)
    for key, value in remaining.items():
        if lines and lines[-1].strip():
            lines.append("")
        lines.append(f"{key}={value}")
    text = "\n".join(lines).rstrip() + "\n"
    target.write_text(text, encoding="utf-8")
    try:
        os.chmod(target, 0o600)
    except OSError:
        pass
    return target


def remove_env_keys(keys: set[str], *, path: Path | None = None) -> Path:
    target = path or crew_env_path()
    if not target.is_file():
        return target
    kept: list[str] = []
    for line in target.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        drop = False
        for key in keys:
            if stripped.startswith(f"{key}="):
                drop = True
                break
        if not drop:
            kept.append(line)
    text = "\n".join(kept).rstrip() + "\n"
    target.write_text(text, encoding="utf-8")
    return target


def upsert_env_file(launcher: Path) -> Path:
    return upsert_env_values(
        {
            KEY: str(launcher.resolve()),
            "CURSOR_CREW_MODEL": "cursor-grok-4.6-xhigh",
            "CURSOR_CREW_LITE_MODEL": "cursor-grok-4.6-high-fast",
            "CURSOR_CREW_TRACE": "1",
            "CURSOR_CREW_SKIP_MCP": "0",
            "CURSOR_CREW_BRIDGE_LOG": str(PROJECT_DIR / "bridge.log"),
        }
    )
