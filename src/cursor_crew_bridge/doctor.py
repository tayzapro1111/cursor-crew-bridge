"""Preflight checks. Never print tokens or full auth DB paths with secrets."""

from __future__ import annotations

import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

from cursor_crew_bridge.config import (
    BRIDGE_VERSION,
    discover_project_dir,
    kirocrew_exe,
    official_kiro_cli,
    shim_kiro_cli,
)
from cursor_crew_bridge.cursor_auth import access_token, cached_email


@dataclass
class Check:
    id: str
    ok: bool
    required: bool
    title: str
    detail: str
    hint: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _python_check() -> Check:
    ver = sys.version_info
    ok = ver >= (3, 11)
    return Check(
        id="python",
        ok=ok,
        required=True,
        title="Python 3.11+",
        detail=f"{ver.major}.{ver.minor}.{ver.micro} ({sys.executable})",
        hint="" if ok else "Install Python 3.11+ and re-run setup.bat (Windows) or ./setup.sh",
    )


def _project_check() -> Check:
    root = discover_project_dir()
    ok = (root / "pyproject.toml").is_file()
    return Check(
        id="project",
        ok=ok,
        required=True,
        title="Project folder",
        detail=str(root),
        hint="" if ok else "Set CURSOR_CREW_HOME to the cloned repo path",
    )


def _shim_check() -> Check:
    shim = shim_kiro_cli()
    ok = shim.is_file()
    return Check(
        id="shim",
        ok=ok,
        required=True,
        title="Bridge launcher (kiro-cli shim)",
        detail=str(shim),
        hint="" if ok else "Run setup.bat or ./setup.sh so pip creates .venv/.../kiro-cli",
    )


def _crew_check() -> Check:
    exe = kirocrew_exe()
    ok = exe.is_file()
    return Check(
        id="kirocrew",
        ok=ok,
        required=True,
        title="Kiro Crew desktop app",
        detail=str(exe),
        hint="" if ok else "Install Kiro Crew, or set KIROCREW_EXE to KiroCrew.exe",
    )


def _token_check() -> Check:
    token = bool(access_token())
    email = cached_email()
    detail = "Cursor session found"
    if email:
        detail += f" ({email})"
    elif token:
        detail += " (email hidden)"
    else:
        detail = "no Cursor login in the IDE database"
    return Check(
        id="cursor_login",
        ok=token,
        required=True,
        title="Cursor login (local IDE session)",
        detail=detail,
        hint=""
        if token
        else "Open Cursor, sign in once, then you can close the IDE. Token stays on this PC.",
    )


def _agent_check() -> Check:
    try:
        from cursor_crew_bridge.cursor_cli import cursor_agent_argv

        argv = cursor_agent_argv()
        return Check(
            id="cursor_agent",
            ok=True,
            required=True,
            title="Cursor Agent CLI",
            detail=" ".join(argv[:2]),
            hint="",
        )
    except FileNotFoundError as exc:
        return Check(
            id="cursor_agent",
            ok=False,
            required=True,
            title="Cursor Agent CLI",
            detail=str(exc),
            hint="Windows: irm https://cursor.com/install?win32=true | iex   macOS/Linux: curl https://cursor.com/install -fsSL | bash",
        )


def _official_check() -> Check:
    official = official_kiro_cli()
    ok = official.is_file()
    return Check(
        id="official_kiro",
        ok=ok,
        required=False,
        title="Official kiro-cli (only for Kiro-subscription mode)",
        detail=str(official),
        hint="" if ok else "Needed only if you click start-kiro-default.bat",
    )


def run_checks() -> list[Check]:
    return [
        _python_check(),
        _project_check(),
        _shim_check(),
        _crew_check(),
        _token_check(),
        _agent_check(),
        _official_check(),
    ]


def required_failed(checks: list[Check]) -> list[Check]:
    return [item for item in checks if item.required and not item.ok]


def format_report(checks: list[Check]) -> str:
    lines = [f"cursor-crew-bridge {BRIDGE_VERSION} doctor", ""]
    for item in checks:
        mark = "OK" if item.ok else ("MISSING" if item.required else "SKIP")
        lines.append(f"[{mark}] {item.title}")
        lines.append(f"      {item.detail}")
        if item.hint and not item.ok:
            lines.append(f"      -> {item.hint}")
    failed = required_failed(checks)
    lines.append("")
    if failed:
        names = ", ".join(item.id for item in failed)
        lines.append(f"Not ready: {names}")
    else:
        lines.append("Ready. Next: start-cursor-gateway.bat")
    return "\n".join(lines)


def doctor_payload() -> dict[str, Any]:
    checks = run_checks()
    return {
        "version": BRIDGE_VERSION,
        "project": str(discover_project_dir()),
        "ok": not required_failed(checks),
        "checks": [item.as_dict() for item in checks],
    }
