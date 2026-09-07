"""Make sure Cursor ACP can write its per-cwd worker.log."""

from __future__ import annotations

import os
from pathlib import Path


def _slugs_for(cwd: str) -> list[str]:
    raw = os.path.abspath(cwd)
    slugs: list[str] = []
    seen: set[str] = set()

    def add(value: str) -> None:
        if value and value not in seen:
            seen.add(value)
            slugs.append(value)

    base = raw.replace(":", "").replace("\\", "-").replace("/", "-")
    add(base)
    add(base.replace("_", "-"))
    add(base.replace("_", ""))
    if base:
        add(base[0].lower() + base[1:])
        add(base[0].upper() + base[1:])
    return slugs


def prepare_cwd(cwd: str | None) -> str:
    """Create cwd + Cursor project worker.log paths. Return an existing directory."""

    fallback = Path(r"D:\Razrabotka\cursor-crew-bridge")
    path = Path(cwd) if cwd and str(cwd).strip() else fallback
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError:
        fallback.mkdir(parents=True, exist_ok=True)
        path = fallback
    resolved = str(path.resolve()) if path.exists() else str(path)
    projects = Path.home() / ".cursor" / "projects"
    for slug in _slugs_for(resolved):
        target = projects / slug
        try:
            target.mkdir(parents=True, exist_ok=True)
            (target / "worker.log").touch()
        except OSError:
            continue
    return resolved
