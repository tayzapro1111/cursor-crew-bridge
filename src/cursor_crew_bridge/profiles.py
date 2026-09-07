"""Switch Crew between Cursor gateway and official kiro-cli."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from cursor_crew_bridge.agent_mcp import mcp_servers_for_acp
from cursor_crew_bridge.config import (
    CONTEXT_WINDOW_TOKENS,
    DEFAULT_AGENT_NAME,
    DEFAULT_MODEL,
    PROJECT_DIR,
    agents_dir,
    data_home,
    gateway_window_keys,
    kirocrew_exe,
    official_kiro_cli,
    shim_kiro_cli,
)
from cursor_crew_bridge.cursor_auth import access_token, cached_email
from cursor_crew_bridge.install_env import remove_env_keys, upsert_env_values
from cursor_crew_bridge.reaper import list_acp_leaks


CURSOR_CREW_KEYS = {
    "CURSOR_CREW_MODEL",
    "CURSOR_CREW_SKIP_MCP",
    "CURSOR_CREW_BRIDGE_LOG",
}


def _patch_json(path: Path, mutator: Any) -> None:
    if not path.is_file():
        return
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return
    mutator(data)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _patch_crew_config(*, model: str, gateway: bool) -> None:
    def mutate(data: dict[str, Any]) -> None:
        agent = data.setdefault("agent", {})
        session = data.setdefault("session", {})
        agent["model"] = model
        agent["provider"] = "acp"
        # Native Crew default: pre-create the ACP session while the user
        # thinks. False hid the 40s 14-MCP handshake until the first prompt
        # and made Grok feel unlike built-in Claude.
        session["eager_spawn"] = True
        if gateway:
            agent["session_start_timeout_secs"] = 900
            agent["chat_turn_timeout_secs"] = 86400
            agent["tool_approval_timeout_secs"] = 7200
            agent["spawn_min_memory_gb"] = 0
            agent["resource_pressure_gb"] = 0
            agent["resource_critical_gb"] = 0
            agent["admission_gate"] = False
            agent["mcp_quarantine_after_failures"] = 0
            agent["completion_keep_chars"] = 0
            session["timeout_secs"] = 86400
            session["watchdog_rss_max_mb"] = 0
            dashboard = data.setdefault("dashboard", {})
            dashboard["mcp_probe_timeout_secs"] = 120
            dashboard["loop_stall_exit_after_secs"] = 300
            orch = data.setdefault("orchestrator", {})
            # Extra High thinking burns the stock 30m stage ceiling.
            orch["stage_timeout_seconds"] = 3600
            gw = data.setdefault("mcp_gateway", {})
            stubs = gw.get("stub_servers")
            wanted = {"kirocrew-core"}
            if isinstance(stubs, list):
                wanted.update(s for s in stubs if isinstance(s, str) and s)
            gw["stub_servers"] = sorted(wanted)
        else:
            agent["session_start_timeout_secs"] = 90
            agent["spawn_min_memory_gb"] = 4.0
            agent["resource_pressure_gb"] = 4.0
            agent["resource_critical_gb"] = 2.0
            session["eager_spawn"] = True

    _patch_json(data_home() / "config.json", mutate)


def _patch_agent_model(model: str) -> None:
    path = agents_dir() / f"{DEFAULT_AGENT_NAME}.json"
    _patch_json(path, lambda data: data.__setitem__("model", model))


def _patch_model_windows(*, gateway: bool) -> None:
    path = data_home() / "model_windows.json"
    if gateway:
        current: dict[str, Any] = {}
        if path.is_file():
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                loaded = {}
            if isinstance(loaded, dict):
                current = loaded
        for key in gateway_window_keys():
            current[key] = CONTEXT_WINDOW_TOKENS
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(current, ensure_ascii=False) + "\n", encoding="utf-8")
        return


def apply_gateway() -> dict[str, Any]:
    launcher = shim_kiro_cli()
    if not launcher.is_file():
        raise FileNotFoundError(f"shim kiro-cli missing: {launcher}")
    upsert_env_values(
        {
            "KIROCREW_KIRO_BIN": str(launcher.resolve()),
            "CURSOR_CREW_MODEL": DEFAULT_MODEL,
            "CURSOR_CREW_LITE_MODEL": "cursor-grok-4.6-high-fast",
            "CURSOR_CREW_TRACE": "1",
            "CURSOR_CREW_SKIP_MCP": "0",
            "CURSOR_CREW_BRIDGE_LOG": str(PROJECT_DIR / "bridge.log"),
        }
    )
    _patch_crew_config(model=DEFAULT_MODEL, gateway=True)
    _patch_agent_model(DEFAULT_MODEL)
    _patch_model_windows(gateway=True)
    return status_payload("gateway")


def apply_default() -> dict[str, Any]:
    official = official_kiro_cli()
    if not official.is_file():
        raise FileNotFoundError(f"official kiro-cli missing: {official}")
    upsert_env_values({"KIROCREW_KIRO_BIN": str(official.resolve())})
    remove_env_keys(CURSOR_CREW_KEYS)
    _patch_crew_config(model="auto", gateway=False)
    _patch_agent_model("auto")
    _patch_model_windows(gateway=False)
    return status_payload("default")


def status_payload(profile: str | None = None) -> dict[str, Any]:
    token = bool(access_token())
    email = cached_email()
    mcp = mcp_servers_for_acp(DEFAULT_AGENT_NAME)
    leaks = list_acp_leaks()
    return {
        "profile": profile or "",
        "shim": str(shim_kiro_cli()),
        "official_kiro": str(official_kiro_cli()),
        "kirocrew": str(kirocrew_exe()),
        "model": DEFAULT_MODEL if profile == "gateway" else ("auto" if profile == "default" else ""),
        "context_window_tokens": CONTEXT_WINDOW_TOKENS if profile == "gateway" else "",
        "mcp_count": len(mcp),
        "mcp_names": [item.get("name") for item in mcp],
        "token_present": token,
        "email_present": bool(email),
        "acp_leaks": [{"pid": item.pid, "name": item.name} for item in leaks],
    }
