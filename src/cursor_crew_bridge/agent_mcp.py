"""Load ~/.kiro/agents/<name>.json MCP servers at runtime. Do not copy secrets."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from cursor_crew_bridge.config import DEFAULT_AGENT_NAME, agents_dir, data_home


def _read_json(path: Path) -> dict[str, Any]:
    try:
        import json

        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def load_agent_spec(agent: str | None) -> dict[str, Any]:
    name = (agent or DEFAULT_AGENT_NAME).strip() or DEFAULT_AGENT_NAME
    direct = agents_dir() / f"{name}.json"
    if direct.is_file():
        return _read_json(direct)
    for path in agents_dir().glob("*.json"):
        data = _read_json(path)
        if data.get("name") == name:
            return data
    return {}


def to_cursor_mcp(entry: dict[str, Any], name: str) -> dict[str, Any] | None:
    command = entry.get("command")
    url = entry.get("url")
    has_cmd = isinstance(command, str) and bool(command.strip())
    has_url = isinstance(url, str) and bool(url.strip())
    if not has_cmd and not has_url:
        return None
    args = entry.get("args")
    env_list: list[dict[str, str]] = []
    raw_env = entry.get("env")
    if isinstance(raw_env, dict):
        env_list = [{"name": str(k), "value": str(v)} for k, v in raw_env.items()]
    elif isinstance(raw_env, list):
        for item in raw_env:
            if isinstance(item, dict) and item.get("name") is not None:
                env_list.append({"name": str(item["name"]), "value": str(item.get("value", ""))})
            elif isinstance(item, str) and "=" in item:
                key, value = item.split("=", 1)
                env_list.append({"name": key, "value": value})
    out: dict[str, Any] = {"name": str(name), "env": env_list}
    if has_cmd:
        out["command"] = command
        out["args"] = [str(part) for part in args] if isinstance(args, list) else []
    if has_url:
        out["url"] = str(url).strip()
    if isinstance(entry.get("cwd"), str) and entry["cwd"].strip():
        out["cwd"] = str(entry["cwd"])
    if isinstance(entry.get("headers"), (dict, list)):
        out["headers"] = entry["headers"]
    server_type = entry.get("type")
    if isinstance(server_type, str) and server_type.strip():
        out["type"] = server_type.strip()
    elif has_url and not has_cmd:
        out["type"] = "http"
    return out


CREW_IDENTITY_SERVERS = frozenset({"kirocrew-core", "kirocrew-dashboard"})


WRAPPER_MARKERS = ("_kirocrew_mcp_gateway_wrapped", "_mc_mcp_gateway_wrapped")


def gateway_overlay_dir() -> Path:
    return data_home() / "mcp-gateway" / "agents"


def _servers_from_mapping(raw: Any, *, wrappers_only: bool = False) -> list[dict[str, Any]]:
    if not isinstance(raw, dict):
        return []
    servers: list[dict[str, Any]] = []
    for name, entry in raw.items():
        if not isinstance(entry, dict):
            continue
        if wrappers_only and not any(entry.get(marker) for marker in WRAPPER_MARKERS):
            continue
        converted = to_cursor_mcp(entry, str(name))
        if converted:
            servers.append(converted)
    return servers


def overlay_mcp_servers(agent: str | None) -> list[dict[str, Any]]:
    """Broker stubs Crew injects on session/new for claude; kiro-cli gets them via --agent overlay."""

    name = (agent or DEFAULT_AGENT_NAME).strip() or DEFAULT_AGENT_NAME
    overlay_dir = gateway_overlay_dir()
    spec = _read_json(overlay_dir / f"{name}.json")
    if not spec and overlay_dir.is_dir():
        try:
            candidates = sorted(overlay_dir.glob(f"*{name}.json"))
        except OSError:
            candidates = []
        for path in candidates:
            data = _read_json(path)
            if data.get("name") == name:
                spec = data
                break
    return _servers_from_mapping(spec.get("mcpServers"), wrappers_only=True)


MCP_SERVER_INITIALIZED = "_kiro.dev/mcp/server_initialized"


def mcp_initialized_notifications(
    session_id: str,
    servers: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """kiro-cli emits these after session/new; Cursor ACP does not."""

    frames: list[dict[str, Any]] = []
    seen: set[str] = set()
    for server in servers or []:
        name = str(server.get("name") or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        params: dict[str, Any] = {"serverName": name}
        if session_id:
            params["sessionId"] = session_id
        frames.append({"jsonrpc": "2.0", "method": MCP_SERVER_INITIALIZED, "params": params})
    return frames

def mcp_servers_for_acp(agent: str | None) -> list[dict[str, Any]]:
    spec = load_agent_spec(agent)
    return _servers_from_mapping(spec.get("mcpServers"))


def resolved_mcp_servers(agent: str | None, incoming: list[Any] | None = None) -> list[dict[str, Any]]:
    """session/new roster: Crew stubs, then gateway overlay, then agent spec. Native includeMcpJson is false."""

    extra = merge_mcp_servers(overlay_mcp_servers(agent), mcp_servers_for_acp(agent))
    return merge_mcp_servers(list(incoming or []), extra)

def merge_mcp_servers(incoming: list[Any], extra: list[Any]) -> list[dict[str, Any]]:
    """Crew-injected stubs win on name so kirocrew-core keeps gateway identity."""

    unique: list[dict[str, Any]] = []
    names: set[str] = set()
    for server in normalize_mcp_servers(list(incoming) + list(extra)):
        name = str(server.get("name") or "")
        if name and name in names:
            continue
        if name:
            names.add(name)
        unique.append(server)
    return unique


def normalize_mcp_servers(servers: list[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for server in servers:
        if not isinstance(server, dict):
            continue
        name = str(server.get("name") or "")
        converted = to_cursor_mcp(server, name or f"mcp{len(out)}")
        if converted:
            out.append(converted)
    return out
