"""Resolve the real Cursor Agent CLI, never xAI's grok `agent.exe`."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from cursor_crew_bridge.config import GROK_BIN_MARKER, log_path
from cursor_crew_bridge.cursor_auth import access_token, cached_email, child_env

WORKER_INDEX = (
    Path.home()
    / "AppData"
    / "Roaming"
    / "Cursor"
    / "User"
    / "globalStorage"
    / "anysphere.cursor-agent-worker"
    / "agent-cli"
    / ".local"
    / "share"
    / "cursor-agent"
)


def _log(message: str) -> None:
    try:
        with log_path().open("a", encoding="utf-8") as handle:
            handle.write(message.rstrip() + "\n")
    except OSError:
        pass


def _is_grok_agent(path: Path) -> bool:
    normalized = os.path.normcase(str(path.resolve())) if path.exists() else os.path.normcase(str(path))
    return normalized == GROK_BIN_MARKER or "\\.grok\\bin\\" in normalized or "/.grok/bin/" in normalized.replace("\\", "/")


def _node() -> str | None:
    override = os.environ.get("CURSOR_CREW_NODE", "").strip()
    if override and Path(override).is_file():
        return override
    found = shutil.which("node")
    return found


def _latest_worker_index() -> Path | None:
    versions = WORKER_INDEX / "versions"
    if not versions.is_dir():
        return None
    dirs = [p for p in versions.iterdir() if p.is_dir() and (p / "index.js").is_file()]
    if not dirs:
        return None
    dirs.sort(key=lambda p: p.name, reverse=True)
    return dirs[0] / "index.js"


def _looks_like_cursor_cli(argv: list[str]) -> bool:
    try:
        result = subprocess.run(
            [*argv, "--version"],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    text = (result.stdout or "") + (result.stderr or "")
    lowered = text.lower()
    if "grok" in lowered and "cursor" not in lowered:
        return False
    if result.returncode != 0 and not text.strip():
        return False
    return True


def cursor_agent_argv() -> list[str]:
    """Return argv that starts Cursor Agent CLI (not xAI grok)."""

    override = os.environ.get("CURSOR_AGENT_BIN", "").strip()
    if override:
        path = Path(override)
        if path.suffix.lower() == ".js":
            node = _node()
            if not node:
                raise FileNotFoundError("CURSOR_AGENT_BIN is a JS file but node.exe was not found")
            return [node, str(path)]
        return [str(path)]

    home = Path.home()
    named = [
        home / ".local" / "bin" / "cursor-agent.exe",
        home / ".local" / "bin" / "cursor-agent.cmd",
        home / ".cursor" / "bin" / "cursor-agent.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "cursor-agent" / "agent.exe",
    ]
    for candidate in named:
        if candidate.is_file() and not _is_grok_agent(candidate):
            return [str(candidate)]

    local_agent = home / ".local" / "bin" / "agent.exe"
    if local_agent.is_file() and not _is_grok_agent(local_agent):
        argv = [str(local_agent)]
        if _looks_like_cursor_cli(argv):
            return argv

    which_agent = shutil.which("cursor-agent")
    if which_agent and not _is_grok_agent(Path(which_agent)):
        return [which_agent]

    index = _latest_worker_index()
    node = _node()
    if index and node:
        argv = [node, str(index)]
        if _looks_like_cursor_cli(argv):
            return argv
        _log(f"worker index present but --version failed: {index}")

    raise FileNotFoundError(
        "Cursor Agent CLI not found. Install it with: "
        "irm 'https://cursor.com/install?win32=true' | iex"
    )


def acp_argv(*, model: str, extra: list[str] | None = None) -> list[str]:
    argv = cursor_agent_argv()
    token = access_token()
    flags: list[str] = []
    if token:
        flags.extend(["--auth-token", token])
    flags.extend(
        [
            "--model",
            model,
            "--trust",
            "--force",
            "--approve-mcps",
            "--disable-auto-update",
        ]
    )
    if extra:
        flags.extend(extra)
    flags.append("acp")
    return argv + flags


def redacted_argv(argv: list[str]) -> list[str]:
    out = []
    skip = False
    for item in argv:
        if skip:
            out.append("<redacted>")
            skip = False
            continue
        if item == "--auth-token":
            out.append(item)
            skip = True
            continue
        out.append(item)
    return out


def status_json() -> dict:
    argv = cursor_agent_argv()
    try:
        result = subprocess.run(
            [*argv, "status", "--format", "json"],
            capture_output=True,
            text=True,
            timeout=25,
            check=False,
            env=child_env(),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "error": str(exc)}
    raw = (result.stdout or "").strip()
    if not raw:
        return {
            "ok": result.returncode == 0,
            "text": (result.stderr or "").strip(),
            "returncode": result.returncode,
        }
    try:
        start = raw.find("{")
        payload = json.loads(raw[start:]) if start >= 0 else json.loads(raw)
    except json.JSONDecodeError:
        return {"ok": result.returncode == 0, "text": raw, "returncode": result.returncode}
    if isinstance(payload, dict):
        payload["ok"] = result.returncode == 0
        payload["returncode"] = result.returncode
        return payload
    return {"ok": result.returncode == 0, "text": raw, "returncode": result.returncode}


def kiro_whoami_json() -> dict[str, str]:
    try:
        status = status_json()
    except FileNotFoundError:
        status = {"ok": False}
    email = ""
    for key in ("email", "accountEmail", "userEmail"):
        value = status.get(key)
        if isinstance(value, str) and value:
            email = value
            break
    auth = status.get("auth")
    if not email and isinstance(auth, dict):
        value = auth.get("email") or auth.get("user")
        if isinstance(value, str):
            email = value
    if not email:
        email = cached_email()
    logged_in = bool(
        status.get("isAuthenticated")
        or status.get("loggedIn")
        or status.get("ok")
        and status.get("status") not in {"unauthenticated", "logged_out"}
        or email
    )
    if not email:
        email = os.environ.get("CURSOR_CREW_WHOAMI_EMAIL", "cursor-local@localhost")
    return {
        "email": email,
        "accountType": "Cursor",
        "startUrl": "",
        "authMethod": "cursor-agent",
        "loggedIn": bool(logged_in),
    }


def print_version() -> None:
    argv = cursor_agent_argv()
    try:
        result = subprocess.run(
            [*argv, "--version"],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
            env=child_env(),
        )
        extra = (result.stdout or result.stderr or "").strip().splitlines()
        suffix = extra[0] if extra else "cursor-agent"
    except (OSError, subprocess.TimeoutExpired):
        suffix = "cursor-agent"
    sys.stdout.write(f"kiro-cli 2.15.0-cursor-crew-bridge ({suffix})\n")
    sys.stdout.flush()
