"""Identify leaked Cursor ACP workers. Never touch Next.js, Cursor IDE, or other apps."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass


KEEP_MARKERS = (
    "testcscase",
    "next\\dist\\server",
    "next/dist/server",
    "start-server.js",
    "vite",
    "chrome-devtools-mcp",
    "storm-tools",
)

ACP_MARKERS = (
    "anysphere.cursor-agent-worker",
    "cursor-agent",
    ".local\\share\\cursor-agent",
    ".local/share/cursor-agent",
)

ACP_FLAGS = (" acp", " --auth-token", "cursor-grok-4.6", "--model cursor-grok")


@dataclass(frozen=True)
class ProcInfo:
    pid: int
    name: str
    command: str


def classify_command(name: str, command: str) -> str:
    """Return 'keep', 'acp-leak', or 'other'."""

    blob = f"{name} {command}".lower().replace("/", "\\")
    if any(marker.lower().replace("/", "\\") in blob for marker in KEEP_MARKERS):
        return "keep"
    if name.lower() in {"cursor.exe", "cursor"}:
        return "keep"
    has_agent = any(marker.lower().replace("/", "\\") in blob for marker in ACP_MARKERS)
    has_flag = any(flag.lower() in blob for flag in ACP_FLAGS)
    if has_agent and has_flag:
        return "acp-leak"
    return "other"


def _cim_processes() -> list[ProcInfo]:
    script = (
        "Get-CimInstance Win32_Process | "
        "Where-Object { $_.Name -match 'node|kiro-cli|KiroCrew|python' } | "
        "Select-Object ProcessId,Name,CommandLine | ConvertTo-Json -Compress -Depth 3"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            timeout=40,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    raw = (result.stdout or "").strip()
    if not raw:
        return []
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if isinstance(payload, dict):
        payload = [payload]
    out: list[ProcInfo] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        try:
            pid = int(item.get("ProcessId") or 0)
        except (TypeError, ValueError):
            continue
        if pid <= 0:
            continue
        out.append(
            ProcInfo(
                pid=pid,
                name=str(item.get("Name") or ""),
                command=str(item.get("CommandLine") or ""),
            )
        )
    return out


def list_acp_leaks() -> list[ProcInfo]:
    return [proc for proc in _cim_processes() if classify_command(proc.name, proc.command) == "acp-leak"]


def kill_pids(pids: list[int]) -> list[int]:
    killed: list[int] = []
    for pid in pids:
        try:
            result = subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if result.returncode == 0:
            killed.append(pid)
    return killed


def reap_acp_leaks() -> list[ProcInfo]:
    leaks = list_acp_leaks()
    kill_pids([proc.pid for proc in leaks])
    return leaks
