"""Parity with native Kiro Crew that Cursor ACP does not emit by itself.

Native kiro-cli (``kiro-cli acp --agent``):
- loads the agent spec, MCP, resources, and prompt.md / prompt-orchestrator.md
- streams usage_update {used, size} or _kiro.dev/metadata.contextUsagePercentage
- session/load restores {sid}.json; on miss, Crew session/new + conversation_log replay
- compact in-place, then ``_kiro.dev/compaction/status`` ``completed`` / ``failed``

Cursor Agent ACP does not read ``--agent``. This module is the host stand-in:
once-per-session agent prompt + steering resources + a tiny Cursor-RPC delta,
usage meter, compact rotate+seed, and session replay when Cursor cannot session/load.
Memory / embeddings / Kiro-Q stay Crew-side — see ``MEMORY_CHANNELS``.
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any

from cursor_crew_bridge.config import CONTEXT_WINDOW_TOKENS, PROJECT_DIR, data_home, is_lite_agent

_BACKTICK_PATH_RE = re.compile(r"`([^`]+)`")
_EDIT_PREFIX_RE = re.compile(r"^Edit(?:ing)?\s+", re.IGNORECASE)
_TOOL_SESSION_UPDATES = frozenset({"tool_call", "tool_call_update"})
_PATH_KEYS = ("path", "file_path", "filePath")
_MCP_AT_RE = re.compile(r"^@([^/\s]+)/(\S+)")
_MCP_DUNDER_RE = re.compile(r"^mcp__([A-Za-z0-9._-]+)__([A-Za-z0-9._-]+)$")
_CURSOR_SHELL_KINDS = frozenset({"shell", "command", "bash", "terminal", "execute"})
_CURSOR_READ_TOKENS = frozenset({"read", "readfile", "fs_read"})
_CURSOR_WRITE_TOKENS = frozenset({"write", "writefile", "fs_write", "edit", "editing"})
_CURSOR_STRREPLACE_TOKENS = frozenset({"strreplace", "str_replace", "applypatch", "code"})
_CURSOR_SHELL_TOKENS = frozenset({"shell", "bash", "execute_bash", "command", "terminal", "execute"})
_CURSOR_GREP_TOKENS = frozenset({"grep", "rg", "search"})
_CURSOR_GLOB_TOKENS = frozenset({"glob", "glob_file_search", "globfilesearch"})
_CURSOR_WEB_SEARCH_TOKENS = frozenset({"websearch", "web_search"})
_CURSOR_WEB_FETCH_TOKENS = frozenset({"webfetch", "web_fetch"})

CHARS_PER_TOKEN = 4
STAGE_EXECUTE_RE = re.compile(
    r"Execute Stage\s+(\d+)\s+of\s+(\d+)\s+now",
    re.IGNORECASE,
)
PLAN_HEADER = "📋 Plan for:"
PLAN_FOOTER = "[OPTION: Go | Go All | Cancel]"
PLAN_TEMPLATE = (
    f'{PLAN_HEADER} "<task description>"\n\n'
    "Stage 1: <Title>\n"
    "  - <task>\n\n"
    "Stage 2: <Title>\n"
    "  - <task>\n\n"
    "Stage N: Verification\n"
    "  - <verification task>\n\n"
    f"{PLAN_FOOTER}"
)

_ORCH_MARKERS = (
    "this is autopilot",
    "switch to autopilot",
    "slot.mode=orchestrator",
    "mode == \"orchestrator\"",
    "create autopilot plan",
    "📋 plan for:",
    "[option: go | go all | cancel]",
    "🎯 goal:",
    "plan status:",
    "current stage —",
    "current stage --",
)

CURSOR_RPC_DELTA = f"""[KIRO CREW — Cursor ACP delta]
cursor/create_plan is accepted and dropped; Crew never sees it. Autopilot UI is only the plan text plus {PLAN_FOOTER}.
Do not write stage_N_result.md; Crew `_capture_stage_result` writes that file.
Filesystem, shell, and search are Cursor builtins. Product tools (spawn, knowledge, browser, computer, cron, skills, sessions) are the MCP servers on this session. Do not use cursor/task as a Kiro Crew subagent.
"""


def normalize_fs_path(path: str) -> str:
    """Crew's chip does ``path.split('/')``. Keep Windows paths POSIX-looking."""

    return path.replace("\\", "/")


def _basename(path: str) -> str:
    normalized = normalize_fs_path(path).rstrip("/")
    name = normalized.split("/")[-1]
    return name or path


def _looks_like_fs_path(value: str) -> bool:
    text = value.strip()
    if not text or text.lower() == "file":
        return False
    if text.startswith("\\\\"):
        return True
    if len(text) >= 3 and text[1] == ":" and text[0].isalpha():
        return True
    return "/" in text or "\\" in text


def _path_from_mapping(obj: Any) -> str | None:
    if not isinstance(obj, dict):
        return None
    for key in _PATH_KEYS:
        raw = obj.get(key)
        if isinstance(raw, str) and raw.strip() and _looks_like_fs_path(raw):
            return raw.strip()
    return None


def _path_from_title(title: str) -> str | None:
    match = _BACKTICK_PATH_RE.search(title)
    if match:
        candidate = match.group(1).strip()
        if candidate and _looks_like_fs_path(candidate):
            return candidate
    rest = _EDIT_PREFIX_RE.sub("", title).strip()
    if rest and _looks_like_fs_path(rest):
        return rest
    return None


def _path_from_locations(update: dict[str, Any]) -> str | None:
    locations = update.get("locations")
    if not isinstance(locations, list):
        return None
    for item in locations:
        path = _path_from_mapping(item)
        if path:
            return path
    return None


def _path_from_content(update: dict[str, Any]) -> str | None:
    blocks = update.get("content")
    if not isinstance(blocks, list):
        return None
    for block in blocks:
        path = _path_from_mapping(block)
        if path:
            return path
    return None


def _tool_path(update: dict[str, Any]) -> str | None:
    raw = update.get("rawInput") or update.get("input")
    return (
        _path_from_mapping(raw)
        or _path_from_locations(update)
        or _path_from_content(update)
        or _path_from_title(str(update.get("title") or ""))
    )


def _merge_raw_input_path(raw: Any, path: str) -> dict[str, Any]:
    out = dict(raw) if isinstance(raw, dict) else {}
    norm = normalize_fs_path(path)
    found = False
    for key in _PATH_KEYS:
        val = out.get(key)
        if isinstance(val, str) and val.strip():
            out[key] = normalize_fs_path(val)
            found = True
    if not found:
        out["path"] = norm
    elif "path" not in out:
        out["path"] = norm
    return out


def _is_edit_update(update: dict[str, Any], title: str) -> bool:
    kind = update.get("kind")
    if isinstance(kind, str) and kind == "edit":
        return True
    return title.lstrip().lower().startswith("edit")


def enrich_cursor_tool_update(update: dict[str, Any]) -> dict[str, Any]:
    """Rewrite Cursor Edit titles to native kiro-cli ``Editing basename``.

    Crew's pill strips the full path out of the label once a chip is shown.
    Cursor sends ``Edit `D:\\abs\\file.ts```, so the leftover is ``Edit ""``.
    Distinct ``toolCallId``s stay distinct — this never merges rows.
    Empty status titles are left alone so a later in_progress frame cannot
    blank a good pill or replace a diff ``rawInput`` with ``{path}``.
    """

    session = str(update.get("sessionUpdate") or "")
    if session not in _TOOL_SESSION_UPDATES:
        return update
    title = update.get("title")
    if not isinstance(title, str) or not title.strip():
        return update
    if not _is_edit_update(update, title):
        return update
    path = _tool_path(update)
    if not path:
        return update
    name = _basename(path)
    if not name:
        return update
    out = dict(update)
    out["title"] = f"Editing {name}"
    out["rawInput"] = _merge_raw_input_path(update.get("rawInput") or update.get("input"), path)
    if not out.get("kind"):
        out["kind"] = "edit"
    return out

def stamp_kiro_tool_meta(update: dict[str, Any]) -> dict[str, Any]:
    """Stamp Crew-trusted ``_meta.kiro`` and map Cursor kinds to kiro-cli.

    Crew's security/TODO parsers ignore LLM ``title``. They read
    ``_meta.kiro.toolName`` / ``mcpServerName``. Shell is ``kind == "execute"``.
    Existing kiro meta is kept. Display titles stay prose except MCP
    ``@server/tool`` (kiro wrapper spelling).
    """

    if not isinstance(update, dict):
        return update
    session = str(update.get("sessionUpdate") or "")
    if session and session not in _TOOL_SESSION_UPDATES:
        return update
    tool_name, server_name, kind = _infer_kiro_tool(update)
    existing_meta = update.get("_meta") if isinstance(update.get("_meta"), dict) else {}
    existing_kiro = existing_meta.get("kiro") if isinstance(existing_meta.get("kiro"), dict) else {}
    kept_name = existing_kiro.get("toolName")
    kept_server = existing_kiro.get("mcpServerName")
    if isinstance(kept_name, str) and kept_name.strip():
        tool_name = kept_name.strip()
    if isinstance(kept_server, str) and kept_server.strip():
        server_name = kept_server.strip()
    current_kind = str(update.get("kind") or "").strip().lower().replace("-", "_")
    if current_kind in _CURSOR_SHELL_KINDS or kind == "execute":
        kind = "execute"
    elif not kind and current_kind in {"read", "edit", "search"}:
        kind = current_kind
    title = update.get("title")
    skip_title = isinstance(title, str) and title.strip() == ASK_USER_QUESTION_TITLE
    changed = False
    out = dict(update)
    if kind and out.get("kind") != kind:
        out["kind"] = kind
        changed = True
    if tool_name or server_name:
        meta = dict(existing_meta)
        kiro = dict(existing_kiro)
        if tool_name and kiro.get("toolName") != tool_name:
            kiro["toolName"] = tool_name
            changed = True
        if server_name and kiro.get("mcpServerName") != server_name:
            kiro["mcpServerName"] = server_name
            changed = True
        if kiro != existing_kiro:
            meta["kiro"] = kiro
            out["_meta"] = meta
            changed = True
        if (
            server_name
            and tool_name
            and not skip_title
            and (not isinstance(title, str) or not title.startswith("@"))
        ):
            wrapped = f"@{server_name}/{tool_name}"
            if title != wrapped:
                out["title"] = wrapped
                changed = True
    return out if changed else update


def _infer_kiro_tool(update: dict[str, Any]) -> tuple[str, str, str]:
    title = update.get("title") if isinstance(update.get("title"), str) else ""
    raw = update.get("rawInput") if isinstance(update.get("rawInput"), dict) else None
    if raw is None and isinstance(update.get("input"), dict):
        raw = update.get("input")
    kind_in = str(update.get("kind") or "").strip().lower().replace("-", "_")
    mcp_name, mcp_server = _mcp_identity(title, raw, update)
    if mcp_name:
        return mcp_name, mcp_server, ""
    token = _tool_token(title)
    if token in _CURSOR_READ_TOKENS or kind_in == "read":
        return "fs_read", "", "read"
    if token in _CURSOR_GREP_TOKENS or (
        kind_in == "search" and not _title_looks_like_glob(title)
    ):
        return "grep", "", "search"
    if token in _CURSOR_GLOB_TOKENS or _title_looks_like_glob(title):
        return "glob", "", "search"
    if token in _CURSOR_WEB_SEARCH_TOKENS:
        return "web_search", "", "search"
    if token in _CURSOR_WEB_FETCH_TOKENS:
        return "web_fetch", "", "fetch"
    if token in _CURSOR_SHELL_TOKENS or kind_in in _CURSOR_SHELL_KINDS:
        return "execute_bash", "", "execute"
    if isinstance(raw, dict) and isinstance(raw.get("command"), str) and raw["command"].strip():
        return "execute_bash", "", "execute"
    if token in _CURSOR_STRREPLACE_TOKENS or (
        isinstance(raw, dict) and ("old_string" in raw or "oldString" in raw)
    ):
        return "code", "", "edit"
    if token in _CURSOR_WRITE_TOKENS or kind_in in {"edit", "write"} or _is_edit_update(update, title):
        return "fs_write", "", "edit"
    return "", "", ""


def _tool_token(title: str) -> str:
    text = title.strip().strip("`")
    if not text:
        return ""
    match = _MCP_AT_RE.match(text)
    if match:
        return text.lower()
    return re.split(r"[\s:/`]+", text, maxsplit=1)[0].lower().replace("-", "_")


def _title_looks_like_glob(title: str) -> bool:
    token = _tool_token(title)
    if token in _CURSOR_GLOB_TOKENS:
        return True
    return "*" in title or "?" in title or "{" in title


def _mcp_identity(title: str, raw: dict[str, Any] | None, update: dict[str, Any]) -> tuple[str, str]:
    text = title.strip()
    match = _MCP_AT_RE.match(text)
    if match:
        return match.group(2).strip(), match.group(1).strip()
    dunder = _MCP_DUNDER_RE.match(text) or _MCP_DUNDER_RE.match(_tool_token(title))
    if dunder:
        return dunder.group(2), dunder.group(1)
    if isinstance(raw, dict):
        server = raw.get("server") or raw.get("serverName") or raw.get("mcpServerName")
        tool = raw.get("tool") or raw.get("toolName")
        if isinstance(server, str) and server.strip() and isinstance(tool, str) and tool.strip():
            return tool.strip(), server.strip()
    name = update.get("name") if isinstance(update.get("name"), str) else ""
    dunder = _MCP_DUNDER_RE.match(name.strip()) if name else None
    if dunder:
        return dunder.group(2), dunder.group(1)
    return "", ""


def kiro_available_commands() -> list[dict[str, Any]]:
    """Slash commands kiro-cli advertises after session/new."""

    return [
        {"name": "compact", "description": "Compact the conversation context", "meta": {"local": False}},
        {"name": "clear", "description": "Clear session history", "meta": {"local": False}},
        {"name": "context", "description": "Show context window usage", "meta": {"inputType": "panel"}},
        {
            "name": "help",
            "description": "List available slash commands",
            "meta": {"inputType": "selection", "optionsMethod": "_kiro.dev/commands/options"},
        },
        {
            "name": "tools",
            "description": "List available tools",
            "meta": {"inputType": "selection", "optionsMethod": "_kiro.dev/commands/options"},
        },
        {"name": "usage", "description": "Show token and credit usage", "meta": {"inputType": "panel"}},
    ]


def commands_available_notification(session_id: str) -> dict[str, Any]:
    params: dict[str, Any] = {"commands": kiro_available_commands()}
    if session_id:
        params["sessionId"] = session_id
    return {"jsonrpc": "2.0", "method": "_kiro.dev/commands/available", "params": params}


def available_commands_update_message(session_id: str) -> dict[str, Any]:
    commands = [
        {"name": item["name"], "description": item["description"]}
        for item in kiro_available_commands()
    ]
    return {
        "jsonrpc": "2.0",
        "method": "session/update",
        "params": {
            "sessionId": session_id,
            "update": {
                "sessionUpdate": "available_commands_update",
                "availableCommands": commands,
            },
        },
    }


def command_options_result(params: dict[str, Any] | None) -> dict[str, Any]:
    """``_kiro.dev/commands/options`` — Crew/Kantoku expect ``options`` + ``hasMore``."""

    payload = params if isinstance(params, dict) else {}
    command = payload.get("command")
    partial = payload.get("partial")
    name = ""
    if isinstance(command, dict):
        name = str(command.get("command") or command.get("name") or "")
        if not isinstance(partial, str):
            partial = command.get("partial")
    elif isinstance(command, str):
        name = command
    name = name.lstrip("/").strip().lower()
    needle = str(partial or "").strip().lower()
    options = _options_for_command(name)
    if needle:
        options = [
            item
            for item in options
            if needle in str(item.get("value") or "").lower()
            or needle in str(item.get("label") or "").lower()
        ]
    return {"options": options, "hasMore": False}


def _options_for_command(name: str) -> list[dict[str, str]]:
    if name in {"compact", "clear", "context", "usage", ""}:
        labels = {
            "compact": ("compact", "Compact now", "Summarize the thread in place"),
            "clear": ("clear", "Clear history", "Drop the conversation transcript"),
            "context": ("context", "Show context", "Context window used / size"),
            "usage": ("usage", "Show usage", "Tokens and credits for this session"),
            "": ("help", "Help", "Available slash commands"),
        }
        key = name or ""
        value, label, description = labels.get(key, labels[""])
        return [{"value": value, "label": label, "description": description}]
    if name == "help":
        return [
            {
                "value": item["name"],
                "label": f"/{item['name']}",
                "description": str(item["description"]),
            }
            for item in kiro_available_commands()
        ]
    if name == "tools":
        tools = (
            ("fs_read", "Read file"),
            ("fs_write", "Write file"),
            ("code", "Edit / replace"),
            ("execute_bash", "Shell"),
            ("grep", "Search contents"),
            ("glob", "Find files"),
            ("web_search", "Web search"),
            ("web_fetch", "Fetch URL"),
            ("todo_list", "Task list"),
        )
        return [{"value": tool, "label": tool, "description": label} for tool, label in tools]
    return [{"value": name, "label": f"/{name}", "description": ""}]


def estimate_tokens(chars: int) -> int:
    if chars <= 0:
        return 0
    return max(1, int(chars) // CHARS_PER_TOKEN)


def clamp_used(used: int, window: int = CONTEXT_WINDOW_TOKENS) -> int:
    if window <= 0:
        window = CONTEXT_WINDOW_TOKENS
    return min(max(0, int(used)), window)


def prompt_text(params: dict[str, Any]) -> str:
    prompt = params.get("prompt")
    chunks: list[str] = []
    if isinstance(prompt, list):
        for block in prompt:
            if isinstance(block, str):
                chunks.append(block)
            elif isinstance(block, dict) and isinstance(block.get("text"), str):
                chunks.append(block["text"])
    elif isinstance(prompt, str):
        chunks.append(prompt)
    return "\n".join(chunks)


def is_stage_execution(text: str) -> bool:
    return bool(STAGE_EXECUTE_RE.search(text or ""))


def looks_like_orchestrator(text: str, crew_mode: str = "") -> bool:
    mode = (crew_mode or "").strip().lower()
    if mode in {"orchestrator", "autopilot"}:
        return True
    lowered = (text or "").lower()
    return any(marker in lowered for marker in _ORCH_MARKERS)


def remember_orchestrator(text: str, crew_mode: str = "") -> str:
    """Latch Autopilot for the ACP child.

    Crew ``session/set_mode`` sends the agent name (``kirocrew``), never
    ``orchestrator``. Mid-chat Autopilot therefore has no ACP mode bit.
    Once a prompt looks like Autopilot / ``_stage_loop``, keep the latch
    until ``session/new``.
    """

    if looks_like_orchestrator(text, crew_mode) or is_stage_execution(text):
        return "orchestrator"
    return crew_mode


# Cursor has no ~/.kiro/sessions/cli/{sid}.json. Advertising True made Crew
# call session/load; a successful fake new marked FirstTurnState.RESUMED and
# skipped conversation_log replay (empty Grok, full UI).
ADVERTISE_LOAD_SESSION = False


def session_load_error() -> dict[str, Any]:
    """Crew treats this like a missing kiro {sid}.json and does session/new + replay."""

    return {
        "code": -32001,
        "message": "cursor-crew-bridge: no native kiro session file; use session/new and replay conversation_log",
    }


# Crew ``context.RECALL_ROLES``. The bridge does not write JSONL. After
# session/new it *replaces* Crew's 80k tail inside the existing
# ``[CONVERSATION HISTORY]`` markers — it does not prepend a second copy.
REPLAY_ROLES = frozenset({"user", "assistant", "inject"})
REPLAY_SKIP_ROLES = frozenset({"tool", "thought", "system", "usage"})
REPLAY_BUDGET_CHARS = 80_000
# Compact seed / recycle thread cover the whole conversation_log (head
# included), not the recycle tail. 120k chars ≈ 30k tokens — ~12% of Extra High.
COMPACT_SUMMARY_BUDGET_CHARS = 120_000
COMPACT_USER_ROW_CHARS = 4_000
COMPACT_ASSISTANT_ROW_CHARS = 400
COMPACT_INJECT_ROW_CHARS = 500
COMPACT_TOOL_ROW_CHARS = 160
COMPACT_TOOL_MAX_ROWS = 80
COMPACT_SEED_PREFACE = (
    "[COMPACT SEED] Full Crew conversation_log (not an 80k tail). "
    "Do not call tools. Reply with one line: COMPACT_OK.\n"
)
REPLAY_THREAD_PREFACE = (
    "[THREAD] Compressed whole-slot history (head included, not an 80k tail). "
    "Answer the CURRENT USER REQUEST below; do not replay this block.\n"
)
CREW_REPLAY_OPEN = "[CONVERSATION HISTORY — recent session replay, tail-heavy, may be truncated]"
CREW_REPLAY_CLOSE = "[END CONVERSATION HISTORY]"

# What is injected vs consciously outside the ACP shim.
MEMORY_CHANNELS = {
    "memory_lessons": "crew_first_prompt",
    "skills": "crew_side",
    "steering": "bridge_steering_texts",
    "embeddings": "out_of_bridge",
    "knowledge_library": "crew_mcp",
    "kiro_q": "absent",
}

COMPACTION_FAILED_SUMMARY = (
    "cursor-crew-bridge: Cursor rotate+seed failed; "
    "Crew will recycle and replay conversation_log"
)
COMPACTION_COMPLETED_SUMMARY = (
    "cursor-crew-bridge: compacted in place — Cursor session rotated, "
    "seeded from the full conversation_log; Crew JSONL unchanged"
)


def is_compact_prompt(text: str) -> bool:
    """True when Crew's first word is ``/compact`` (dashboard + autocompact)."""

    stripped = (text or "").lstrip()
    if not stripped:
        return False
    first = stripped.split(None, 1)[0]
    return first.lower() == "/compact" or first.lower().startswith("/compact")


def is_compact_command(params: dict[str, Any]) -> bool:
    """``_kiro.dev/commands/execute`` object or string form for compact."""

    command = params.get("command")
    if isinstance(command, str):
        return is_compact_prompt(command) or command.lstrip("/").lower() == "compact"
    if isinstance(command, dict):
        name = str(command.get("command") or command.get("name") or "")
        return name.lstrip("/").lower() == "compact"
    return False


LOCAL_SLASH_COMMANDS = frozenset({"help", "tools", "usage", "context", "clear"})


def slash_command_name(text: str) -> str:
    """Bare `/help` (etc.) sent as `session/prompt`. Extra words go to the model."""

    stripped = (text or "").strip()
    if not stripped.startswith("/"):
        return ""
    parts = stripped.split()
    if len(parts) != 1:
        return ""
    name = parts[0].lstrip("/").split("?", 1)[0].lower()
    if name in LOCAL_SLASH_COMMANDS:
        return name
    return ""


def last_prompt_block(params: dict[str, Any]) -> str:
    """Last text block of a Crew prompt. History/inject live in earlier blocks."""

    prompt = params.get("prompt") if isinstance(params, dict) else None
    if isinstance(prompt, list):
        for block in reversed(prompt):
            if isinstance(block, str) and block.strip():
                return block.strip()
            if isinstance(block, dict) and isinstance(block.get("text"), str) and block["text"].strip():
                return block["text"].strip()
        return ""
    if isinstance(prompt, str):
        return prompt.strip()
    return prompt_text(params).strip() if isinstance(params, dict) else ""


def execute_command_name(params: dict[str, Any]) -> str:
    """`_kiro.dev/commands/execute` object or string form."""

    command = params.get("command") if isinstance(params, dict) else None
    if isinstance(command, str):
        token = command.strip().split(None, 1)[0] if command.strip() else ""
        return token.lstrip("/").split("?", 1)[0].lower()
    if isinstance(command, dict):
        name = str(command.get("command") or command.get("name") or "")
        return name.lstrip("/").split("?", 1)[0].lower()
    return ""


def local_slash_reply(name: str, used: int = 0, window: int = CONTEXT_WINDOW_TOKENS) -> str | None:
    """Native kiro-cli answers these locally. Compact stays on the rotate+seed path."""

    key = (name or "").lstrip("/").lower()
    if key == "help":
        lines = ["Available commands:", ""]
        lines.extend(
            f"/{item['name']} — {item['description']}" for item in kiro_available_commands()
        )
        return "\n".join(lines) + "\n"
    if key == "tools":
        lines = ["Available tools:", ""]
        for item in _options_for_command("tools"):
            label = item.get("label") or item.get("value") or ""
            desc = item.get("description") or ""
            lines.append(f"{label} — {desc}" if desc else str(label))
        return "\n".join(lines) + "\n"
    if key in {"usage", "context"}:
        size = window if window > 0 else CONTEXT_WINDOW_TOKENS
        counted = clamp_used(used, size)
        pct = round((counted / size) * 100, 1) if size else 0.0
        return (
            f"Context: {counted:,} / {size:,} tokens ({pct}%).\n"
            "Kiro credits are not available on cursor-crew-bridge (Cursor account).\n"
        )
    if key == "clear":
        return (
            "Start a new chat from the sidebar to drop this thread. "
            "cursor-crew-bridge does not wipe Crew JSONL.\n"
        )
    return None


def local_slash_crew_messages(session_id: str, text: str) -> list[dict[str, Any]]:
    if not session_id or not text:
        return []
    return [
        {
            "jsonrpc": "2.0",
            "method": "session/update",
            "params": {
                "sessionId": session_id,
                "update": {
                    "sessionUpdate": "agent_message_chunk",
                    "content": {"type": "text", "text": text},
                },
            },
        }
    ]


def compaction_status_ack() -> dict[str, Any]:
    """RPC poll: idle. Compact is implemented by the bridge (rotate+seed)."""

    return {"status": "idle", "supported": True}


def compaction_failed_notification(session_id: str = "") -> dict[str, Any]:
    """Last-resort: rotate+seed failed. Crew recycles and replays the 80k tail."""

    params: dict[str, Any] = {
        "status": {"type": "failed", "error": COMPACTION_FAILED_SUMMARY},
        "summary": COMPACTION_FAILED_SUMMARY,
    }
    if session_id:
        params["sessionId"] = session_id
    return {"jsonrpc": "2.0", "method": "_kiro.dev/compaction/status", "params": params}


def compaction_completed_notification(session_id: str = "", summary: str = "") -> dict[str, Any]:
    """Unblock ``wait_for_compaction`` with ``completed`` so Crew does not recycle."""

    text = summary or COMPACTION_COMPLETED_SUMMARY
    params: dict[str, Any] = {
        "status": {"type": "completed", "summary": text},
        "summary": text,
    }
    if session_id:
        params["sessionId"] = session_id
    return {"jsonrpc": "2.0", "method": "_kiro.dev/compaction/status", "params": params}


def compact_prompt_hint(text: str) -> str:
    stripped = (text or "").lstrip()
    if not is_compact_prompt(stripped):
        return ""
    rest = stripped.split(None, 1)
    return rest[1].strip() if len(rest) > 1 else ""


def conversation_log_stem(session_key: str) -> str:
    return re.sub(r"[^\w\-.]", "_", session_key or "")


def conversation_log_path(session_key: str = "") -> Path | None:
    """Crew JSONL for this ACP child. Read-only — never rewrite or truncate."""

    override = os.environ.get("CURSOR_CREW_SESSION_LOG", "").strip()
    if override:
        path = Path(override)
        if path.is_file():
            return path
    key = (session_key or os.environ.get("KIROCREW_SESSION_KEY") or "").strip()
    if not key:
        return None
    path = data_home() / "sessions" / f"{conversation_log_stem(key)}.jsonl"
    return path if path.is_file() else None


def iter_conversation_log_files(path: Path) -> list[Path]:
    """Current JSONL plus older archive segments, oldest first."""

    files: list[Path] = []
    archive = path.parent / "archive"
    if archive.is_dir():
        files.extend(sorted(archive.glob(f"{path.stem}__*.jsonl")))
    files.append(path)
    return files


def _condense_tool_fact(text: str) -> str:
    """One-line fact from a tool row. Never the raw payload."""

    first = (text or "").strip().splitlines()[0].strip() if text else ""
    if not first:
        return ""
    if len(first) > COMPACT_TOOL_ROW_CHARS:
        return first[: COMPACT_TOOL_ROW_CHARS - 1] + "…"
    return first


def load_conversation_rows(path: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    tool_seen: set[str] = set()
    tool_count = 0
    for file in iter_conversation_log_files(path):
        try:
            raw = file.read_text(encoding="utf-8")
        except OSError:
            continue
        for line in raw.splitlines():
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(item, dict):
                continue
            role = str(item.get("role") or "")
            content = item.get("content")
            if not isinstance(content, str) or not content.strip():
                continue
            if role in REPLAY_ROLES:
                rows.append({"role": role, "content": content})
                continue
            if role != "tool" or tool_count >= COMPACT_TOOL_MAX_ROWS:
                continue
            fact = _condense_tool_fact(content)
            if not fact or fact in tool_seen:
                continue
            tool_seen.add(fact)
            tool_count += 1
            rows.append({"role": "tool", "content": fact})
    return rows


def _condense_assistant(text: str, cap: int) -> str:
    keep: list[str] = []
    for line in (text or "").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if (
            stripped.startswith("✅")
            or stripped.startswith("#")
            or "Stage " in stripped
            or stripped.startswith("`")
        ):
            keep.append(stripped)
    body = "\n".join(keep) if keep else (text or "").strip()
    if len(body) <= cap:
        return body
    return body[: max(0, cap - 1)] + "…"


def build_compact_summary(
    rows: list[dict[str, str]],
    *,
    budget: int = COMPACT_SUMMARY_BUDGET_CHARS,
    hint: str = "",
    preface: str | None = None,
) -> str:
    """Extractive summary of the whole log. Users first (head→tail), then tool facts, injects, assistants."""

    header = COMPACT_SEED_PREFACE if preface is None else preface
    if hint:
        header += f"Hint: {hint[:2000]}\n"
    users = [row["content"] for row in rows if row.get("role") == "user"]
    tools = [row["content"] for row in rows if row.get("role") == "tool"]
    injects = [row["content"] for row in rows if row.get("role") == "inject"]
    assistants = [row["content"] for row in rows if row.get("role") == "assistant"]
    parts = [header]
    used = len(header)

    def _add(label: str, text: str, cap: int) -> bool:
        nonlocal used
        clipped = text if len(text) <= cap else text[: cap - 1] + "…"
        block = f"{label}: {clipped}\n"
        if used + len(block) > budget:
            return False
        parts.append(block)
        used += len(block)
        return True

    for text in users:
        if not _add("user", text, COMPACT_USER_ROW_CHARS):
            crumb = text[:200] + ("…" if len(text) > 200 else "")
            if not _add("user", crumb, 220):
                parts.append("…[further user turns omitted]\n")
                break
    for text in tools:
        _add("tool", _condense_tool_fact(text) or text, COMPACT_TOOL_ROW_CHARS)
    for text in injects:
        _add("inject", text, COMPACT_INJECT_ROW_CHARS)
    for text in assistants:
        _add("assistant", _condense_assistant(text, COMPACT_ASSISTANT_ROW_CHARS), COMPACT_ASSISTANT_ROW_CHARS)
    return "".join(parts)


def replace_crew_replay_block(text: str, thread: str) -> str | None:
    """Swap Crew's tail-heavy history for the compressed thread. None if no block."""

    start = (text or "").find(CREW_REPLAY_OPEN)
    end = (text or "").find(CREW_REPLAY_CLOSE)
    if start < 0 or end < 0 or end <= start:
        return None
    close_at = end + len(CREW_REPLAY_CLOSE)
    body = thread.rstrip() + "\n" if thread.strip() else ""
    return text[:start] + CREW_REPLAY_OPEN + "\n" + body + CREW_REPLAY_CLOSE + text[close_at:]


def rewrite_prompt_history(params: dict[str, Any], thread: str) -> tuple[dict[str, Any], bool]:
    """Replace a Crew ``[CONVERSATION HISTORY]`` block inside session/prompt params."""

    out = dict(params)
    prompt = out.get("prompt")
    if isinstance(prompt, str):
        replaced = replace_crew_replay_block(prompt, thread)
        if replaced is None:
            return out, False
        out["prompt"] = replaced
        return out, True
    if not isinstance(prompt, list):
        return out, False
    new_blocks: list[Any] = []
    found = False
    for block in prompt:
        if isinstance(block, str):
            replaced = replace_crew_replay_block(block, thread)
            if replaced is not None:
                new_blocks.append(replaced)
                found = True
                continue
            new_blocks.append(block)
            continue
        if isinstance(block, dict) and isinstance(block.get("text"), str):
            replaced = replace_crew_replay_block(block["text"], thread)
            if replaced is not None:
                item = dict(block)
                item["text"] = replaced
                new_blocks.append(item)
                found = True
                continue
        new_blocks.append(block)
    out["prompt"] = new_blocks
    return out, found


def prompt_end_turn_result(req_id: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "result": {"stopReason": "end_turn"}}


def current_mode_update_message(session_id: str, mode_id: str) -> dict[str, Any]:
    """Crew ``current_mode_update`` — mode bar / parse_session_modes latch."""

    return {
        "jsonrpc": "2.0",
        "method": "session/update",
        "params": {
            "sessionId": session_id,
            "update": {
                "sessionUpdate": "current_mode_update",
                "currentModeId": mode_id,
            },
        },
    }


def usage_update_message(session_id: str, used: int, size: int = CONTEXT_WINDOW_TOKENS) -> dict[str, Any]:
    # Extra High / high-fast are 256k. Ignore Cursor's advertised 1M (and any
    # other caller size) so Crew's meter and autocompact stay on the real cap.
    window = CONTEXT_WINDOW_TOKENS if CONTEXT_WINDOW_TOKENS > 0 else 256_000
    counted = clamp_used(used, window)
    return {
        "jsonrpc": "2.0",
        "method": "session/update",
        "params": {
            "sessionId": session_id,
            "update": {
                "sessionUpdate": "usage_update",
                "used": counted,
                "size": window,
            },
        },
    }


def metadata_percentage_message(session_id: str, used: int, size: int = CONTEXT_WINDOW_TOKENS) -> dict[str, Any]:
    """Native kiro-cli also streams contextUsagePercentage. Crew accepts either."""

    window = CONTEXT_WINDOW_TOKENS if CONTEXT_WINDOW_TOKENS > 0 else 256_000
    counted = clamp_used(used, window)
    pct = round((counted / window) * 100, 1) if window else 0.0
    return {
        "jsonrpc": "2.0",
        "method": "_kiro.dev/metadata",
        "params": {
            "sessionId": session_id,
            "contextUsagePercentage": pct,
        },
    }


def cursor_prompt_used_tokens(result: Any) -> int | None:
    if not isinstance(result, dict):
        return None
    nested = result.get("usage") if isinstance(result.get("usage"), dict) else {}
    for blob in (result, nested):
        for key in ("totalTokens", "total_tokens"):
            raw = blob.get(key)
            if isinstance(raw, bool) or not isinstance(raw, (int, float)):
                continue
            if raw > 0:
                return int(raw)
    keys = (
        "inputTokens",
        "outputTokens",
        "cachedReadTokens",
        "cachedWriteTokens",
        "promptTokens",
        "completionTokens",
        "input_tokens",
        "output_tokens",
    )
    if not any(key in result or key in nested for key in keys):
        return None
    total = 0
    for key in keys:
        raw = result.get(key, nested.get(key))
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            continue
        if raw > 0:
            total += int(raw)
    return total or None


def session_cancel_notification(session_id: str) -> dict[str, Any]:
    """ACP spec: session/cancel is a notification — no JSON-RPC ``id``."""

    return {
        "jsonrpc": "2.0",
        "method": "session/cancel",
        "params": {"sessionId": session_id},
    }


def prompt_cancelled_result(req_id: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "result": {"stopReason": "cancelled"}}


def _todo_text(item: dict[str, Any]) -> str:
    for key in ("content", "text", "title", "task_description", "description"):
        raw = item.get(key)
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
    return ""


def cursor_todos_snapshot(params: dict[str, Any]) -> dict[str, Any] | None:
    """Map ``cursor/update_todos`` into kiro ``todo_list.rawOutput``."""

    items = params.get("todos") or params.get("items") or params.get("tasks")
    if not isinstance(items, list):
        return None
    tasks: list[dict[str, Any]] = []
    for idx, raw in enumerate(items):
        if not isinstance(raw, dict):
            continue
        status = str(raw.get("status") or "").lower()
        completed = bool(raw.get("completed")) or status in {"completed", "complete", "done"}
        task_id = raw.get("id")
        tasks.append(
            {
                "id": str(task_id) if task_id is not None else str(idx + 1),
                "task_description": _todo_text(raw),
                "completed": completed,
            }
        )
    description = params.get("description")
    if not isinstance(description, str):
        description = ""
    return {"description": description, "tasks": tasks}


ASK_USER_QUESTION_TITLE = "AskUserQuestion"
CREATE_PLAN_OUTCOME = {"outcome": {"outcome": "accepted"}}
CREATE_PLAN_MAPPING = "wont"
# Explicit extras mapping — never silent-drop. Crew has no plan/task/image RPCs;
# ask is a tool_call card, not cursor/ask_question.
CURSOR_EXTRAS = {
    "ask_question": "crew_card",
    "create_plan": "wont",
    "update_todos": "todo_list",
    "task": "thought",
    "generate_image": "image_or_ref",
    "permission_options": "name_and_label",
    "session_new_mcp": "incoming_stub_wins",
}


def cursor_ask_crew_payload(params: dict[str, Any]) -> dict[str, Any] | None:
    """Normalize Cursor ``ask_question`` into Crew ``AskUserQuestion`` input.

    Crew ``validate_ask_user_question`` keys on ``question`` / ``label``, not
    Cursor's ``prompt``. Do not put ``description`` on the top-level rawInput —
    ``select_tool_title`` would steal the pill title and the card would not fire.
    """

    raw = params.get("questions") if isinstance(params.get("questions"), list) else []
    questions: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        text = str(item.get("question") or item.get("prompt") or item.get("text") or "").strip()
        if not text:
            continue
        header = str(item.get("header") or item.get("title") or "")[:50]
        options: list[dict[str, str]] = []
        seen: set[str] = set()
        for option in item.get("options") if isinstance(item.get("options"), list) else []:
            if isinstance(option, str) and option.strip():
                label = option.strip()
                desc = ""
            elif isinstance(option, dict):
                label = str(option.get("label") or option.get("id") or option.get("value") or "").strip()
                desc = str(option.get("description") or option.get("detail") or "")
            else:
                continue
            if not label:
                continue
            norm = " ".join(label.split()).casefold()
            if norm in seen:
                continue
            seen.add(norm)
            options.append({"label": label, "description": desc})
        if not options:
            continue
        questions.append(
            {
                "question": text,
                "header": header,
                "options": options,
                "multiSelect": bool(item.get("multiSelect") or item.get("allow_multiple")),
            }
        )
    if not questions:
        return None
    return {"questions": questions}


def cursor_ask_crew_messages(session_id: str, params: dict[str, Any], call_id: str = "cursor-ask") -> list[dict[str, Any]]:
    """Crew ``chat_runner`` opens the card on ``title == AskUserQuestion``.

    Cursor is answered ``skipped`` (never auto-pick). The pill is completed
    immediately so it does not spin — Crew's native MCP ``ask_question`` is
    also stateless (directive + end turn). The user's next message carries
    the choice; there is no ACP wait for a question-card answer.
    """

    payload = cursor_ask_crew_payload(params)
    if not payload or not session_id:
        return []
    open_card = {
        "jsonrpc": "2.0",
        "method": "session/update",
        "params": {
            "sessionId": session_id,
            "update": {
                "sessionUpdate": "tool_call",
                "toolCallId": call_id,
                "title": ASK_USER_QUESTION_TITLE,
                "kind": "other",
                "status": "pending",
                "rawInput": payload,
            },
        },
    }
    done = {
        "jsonrpc": "2.0",
        "method": "session/update",
        "params": {
            "sessionId": session_id,
            "update": {
                "sessionUpdate": "tool_call_update",
                "toolCallId": call_id,
                "title": ASK_USER_QUESTION_TITLE,
                "status": "completed",
                "rawInput": payload,
            },
        },
    }
    return [open_card, done]


def cursor_ask_result() -> dict[str, Any]:
    return {"outcome": {"outcome": "skipped", "reason": "shown as Crew question card; not auto-answered"}}


def cursor_task_text(params: dict[str, Any]) -> str:
    for key in ("text", "content", "title", "description", "message", "prompt"):
        raw = params.get(key)
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
    nested = params.get("task")
    if isinstance(nested, str) and nested.strip():
        return nested.strip()
    if isinstance(nested, dict):
        return cursor_task_text(nested)
    return ""


def cursor_task_crew_messages(session_id: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    """Crew has no ``cursor/task`` RPC. Surface the body as a thought bubble."""

    text = cursor_task_text(params)
    if not text or not session_id:
        return []
    return [
        {
            "jsonrpc": "2.0",
            "method": "session/update",
            "params": {
                "sessionId": session_id,
                "update": {
                    "sessionUpdate": "agent_thought_chunk",
                    "content": {"type": "text", "text": text + "\n"},
                },
            },
        }
    ]


def extract_generated_image(value: Any) -> dict[str, str] | None:
    if not isinstance(value, dict):
        return None
    kind = str(value.get("type") or "").lower()
    mime = value.get("mimeType") or value.get("mime")
    data = value.get("data") or value.get("imageData") or value.get("blob")
    if isinstance(data, str) and data and (kind == "image" or isinstance(mime, str) and str(mime).startswith("image/")):
        return {"type": "image", "data": data, "mimeType": str(mime or "image/png")}
    for item in value.values():
        found = extract_generated_image(item)
        if found:
            return found
        if isinstance(item, list):
            for nested in item:
                found = extract_generated_image(nested)
                if found:
                    return found
    return None


def extract_generated_image_ref(value: Any) -> str:
    """URL or filesystem path when Cursor omits base64 (not silent-drop)."""

    if isinstance(value, str) and value.strip() and (
        value.startswith(("http://", "https://", "file:", "/", "\\\\")) or "\\" in value
    ):
        return value.strip()
    if not isinstance(value, dict):
        return ""
    for key in ("url", "uri", "href", "src", "path", "filePath", "file", "imageUrl"):
        raw = value.get(key)
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
    for item in value.values():
        found = extract_generated_image_ref(item)
        if found:
            return found
        if isinstance(item, list):
            for nested in item:
                found = extract_generated_image_ref(nested)
                if found:
                    return found
    return ""


def generated_image_crew_messages(session_id: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    if not session_id:
        return []
    frames: list[dict[str, Any]] = []
    image = extract_generated_image(params)
    if image:
        frames.append(
            {
                "jsonrpc": "2.0",
                "method": "session/update",
                "params": {
                    "sessionId": session_id,
                    "update": {"sessionUpdate": "agent_message_chunk", "content": image},
                },
            }
        )
    ref = extract_generated_image_ref(params)
    if ref and not image:
        frames.append(
            {
                "jsonrpc": "2.0",
                "method": "session/update",
                "params": {
                    "sessionId": session_id,
                    "update": {
                        "sessionUpdate": "agent_message_chunk",
                        "content": {"type": "text", "text": f"[generated image]({ref})\n"},
                    },
                },
            }
        )
    return frames


def cursor_todos_crew_messages(session_id: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    snap = cursor_todos_snapshot(params)
    if snap is None:
        return []
    meta = {"kiro": {"toolName": "todo_list"}}
    call = {
        "jsonrpc": "2.0",
        "method": "session/update",
        "params": {
            "sessionId": session_id,
            "update": {
                "sessionUpdate": "tool_call",
                "toolCallId": "cursor-todos",
                "title": "Updating task list",
                "kind": "other",
                "status": "in_progress",
                "_meta": meta,
            },
        },
    }
    done = {
        "jsonrpc": "2.0",
        "method": "session/update",
        "params": {
            "sessionId": session_id,
            "update": {
                "sessionUpdate": "tool_call_update",
                "toolCallId": "cursor-todos",
                "title": "Updating task list",
                "status": "completed",
                "_meta": meta,
                "rawOutput": snap,
            },
        },
    }
    return [call, done]


_CANCEL_DROP_UPDATES = frozenset(
    {
        "tool_call",
        "tool_call_update",
        "agent_message_chunk",
        "agent_thought_chunk",
    }
)


def drop_update_after_cancel(kind: str) -> bool:
    return kind in _CANCEL_DROP_UPDATES


def _text_block(text: str) -> dict[str, str]:
    return {"type": "text", "text": text}


def prepend_prompt_blocks(params: dict[str, Any], texts: list[str]) -> dict[str, Any]:
    blocks = [_text_block(item.rstrip() + "\n\n") for item in texts if item.strip()]
    if not blocks:
        return params
    out = dict(params)
    prompt = out.get("prompt")
    if isinstance(prompt, list):
        out["prompt"] = [*blocks, *prompt]
    elif isinstance(prompt, str):
        out["prompt"] = [*blocks, _text_block(prompt)]
    else:
        out["prompt"] = blocks
    return out


AGENT_PROMPT_MARK = "KIRO CREW — prompt.md"
ORCHESTRATOR_MARK = "KIRO CREW AUTOPILOT — native"
STEERING_BUDGET_CHARS = 32_000
ORCHESTRATOR_BUDGET_CHARS = 80_000
_DUMP_STRING_CAP = 400
_DUMP_SECRET_RE = re.compile(
    r"token|secret|password|authorization|auth[-_]?token|api[-_]?key",
    re.I,
)


def _read_text(path: Path, limit: int) -> str:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return ""
    text = text.replace("\r\n", "\n").strip()
    if len(text) > limit:
        return text[:limit].rstrip() + "\n…"
    return text


def prompt_md_candidates(cwd: str = "") -> list[Path]:
    roots: list[Path] = []
    if cwd.strip():
        root = Path(cwd)
        roots.extend(
            [
                root / "agents" / "prompt.md",
                root / ".kiro" / "prompt.md",
            ]
        )
    roots.extend(
        [
            data_home() / "prompt.md",
            Path.home() / ".kiro" / "prompt.md",
            PROJECT_DIR / "KiroCrew-0.5.0" / "src" / "kiro_crew" / "config" / "prompt.md",
        ]
    )
    return roots


def prompt_orchestrator_candidates(cwd: str = "") -> list[Path]:
    roots: list[Path] = []
    if cwd.strip():
        root = Path(cwd)
        roots.extend(
            [
                root / "agents" / "prompt-orchestrator.md",
                root / ".kiro" / "prompt-orchestrator.md",
            ]
        )
    roots.extend(
        [
            data_home() / "prompt-orchestrator.md",
            Path.home() / ".kiro" / "prompt-orchestrator.md",
            PROJECT_DIR / "KiroCrew-0.5.0" / "src" / "kiro_crew" / "config" / "prompt-orchestrator.md",
        ]
    )
    return roots


def load_prompt_orchestrator(cwd: str = "") -> str:
    """Native Autopilot system prompt kiro-cli injects on a new orchestrator session."""

    for path in prompt_orchestrator_candidates(cwd):
        text = _read_text(path, ORCHESTRATOR_BUDGET_CHARS)
        if text:
            return text.replace("{bot_name}", "Kiro Crew")
    return ""


def load_steering_markdown(cwd: str = "") -> str:
    """Agent spec resources: file://.kiro/steering/**/*.md relative to session cwd."""

    if not cwd.strip():
        return ""
    folder = Path(cwd) / ".kiro" / "steering"
    if not folder.is_dir():
        return ""
    chunks: list[str] = []
    used = 0
    try:
        paths = sorted(folder.rglob("*.md"))
    except OSError:
        return ""
    for path in paths:
        body = _read_text(path, STEERING_BUDGET_CHARS)
        if not body:
            continue
        header = f"### {path.relative_to(folder).as_posix()}\n{body}"
        if used + len(header) > STEERING_BUDGET_CHARS:
            break
        chunks.append(header)
        used += len(header)
    if not chunks:
        return ""
    return "[KIRO CREW STEERING]\n" + "\n\n".join(chunks)


def _path_from_prompt_ref(value: str) -> Path | None:
    raw = value.strip()
    if not raw:
        return None
    if raw.startswith("file://"):
        body = raw[7:]
        if body.startswith("/") and len(body) >= 3 and body[2] == ":":
            body = body[1:]
        return Path(body)
    path = Path(raw)
    if path.suffix.lower() == ".md" or path.is_file():
        return path
    return None


def load_agent_prompt(cwd: str = "", *, orchestrator: bool = False, agent: str = "") -> str:
    """kiro-cli ``--agent`` prompt file. Cursor session/new has no systemPrompt."""

    if orchestrator:
        return load_prompt_orchestrator(cwd)
    if agent:
        from cursor_crew_bridge.agent_mcp import load_agent_spec

        raw = load_agent_spec(agent).get("prompt")
        if isinstance(raw, str) and raw.strip():
            path = _path_from_prompt_ref(raw)
            if path is not None:
                text = _read_text(path, ORCHESTRATOR_BUDGET_CHARS)
                if text:
                    return text.replace("{bot_name}", "Kiro Crew")
            elif "file://" not in raw[:12] and len(raw) > 80:
                return raw.replace("{bot_name}", "Kiro Crew")[:ORCHESTRATOR_BUDGET_CHARS]
    for path in prompt_md_candidates(cwd):
        text = _read_text(path, ORCHESTRATOR_BUDGET_CHARS)
        if text:
            return text.replace("{bot_name}", "Kiro Crew")
    return ""


def _redact_acp(value: Any, *, depth: int = 0) -> Any:
    if depth > 6:
        return "…"
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            name = str(key)
            if _DUMP_SECRET_RE.search(name):
                out[name] = "<redacted>"
            else:
                out[name] = _redact_acp(item, depth=depth + 1)
        return out
    if isinstance(value, list):
        head = [_redact_acp(item, depth=depth + 1) for item in value[:20]]
        if len(value) > 20:
            head.append(f"…+{len(value) - 20}")
        return head
    if isinstance(value, str):
        if _DUMP_SECRET_RE.search(value) and len(value) > 12:
            return "<redacted>"
        if len(value) > _DUMP_STRING_CAP:
            return value[:_DUMP_STRING_CAP] + "…"
        return value
    return value


def dump_acp_frame(direction: str, payload: dict[str, Any]) -> None:
    from cursor_crew_bridge.config import dump_acp_path

    path = dump_acp_path()
    if path is None:
        return
    record: dict[str, Any] = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "dir": direction,
        "method": payload.get("method"),
        "id": payload.get("id"),
    }
    if "params" in payload:
        record["params"] = _redact_acp(payload.get("params"))
    if "error" in payload:
        record["error"] = _redact_acp(payload.get("error"))
    if "result" in payload:
        result = payload.get("result")
        if isinstance(result, dict):
            record["result_keys"] = sorted(str(key) for key in result)
        else:
            record["result"] = _redact_acp(result)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        return


def cursor_prompt_capabilities(cursor_caps: dict[str, Any] | None) -> dict[str, Any]:
    raw = {}
    if isinstance(cursor_caps, dict):
        maybe = cursor_caps.get("promptCapabilities")
        if isinstance(maybe, dict):
            raw = maybe
    image = raw.get("image")
    return {
        "image": True if image is None else bool(image),
        "audio": bool(raw.get("audio")),
        "embeddedContext": bool(raw.get("embeddedContext", True)),
    }


def cursor_load_session_supported(cursor_caps: dict[str, Any] | None) -> bool:
    if not isinstance(cursor_caps, dict):
        return False
    return bool(cursor_caps.get("loadSession"))


def crew_client_capabilities(crew_caps: dict[str, Any] | None) -> dict[str, Any]:
    caps = dict(crew_caps) if isinstance(crew_caps, dict) else {}
    fs = caps.get("fs") if isinstance(caps.get("fs"), dict) else {}
    caps["fs"] = {
        "readTextFile": bool(fs.get("readTextFile")),
        "writeTextFile": bool(fs.get("writeTextFile")),
    }
    caps["terminal"] = bool(caps.get("terminal"))
    return caps

def steering_texts(
    params: dict[str, Any],
    *,
    agent: str,
    crew_mode: str,
    already: set[str],
    cwd: str = "",
    first_turn: bool = False,
) -> list[str]:
    """Once-per-session --agent stand-in. Lite/optimizer stay unsteered.

    Native kiro-cli keeps prompt.md / prompt-orchestrator.md as the system
    prompt. Cursor has no --agent, so the real file plus steering resources
    and a tiny Cursor-RPC delta land once. If the session later latches
    Autopilot, ``prompt-orchestrator.md`` is injected once more without
    repeating steering / the RPC delta. Crew already injects memory, skills,
    and [CURRENT AGENT] — do not duplicate those.
    """

    if is_lite_agent(agent):
        return []
    _ = first_turn
    text = prompt_text(params)
    orch = looks_like_orchestrator(text, crew_mode) or is_stage_execution(text)
    extras: list[str] = []
    if "host" not in already:
        already.add("host")
        prompt = load_agent_prompt(cwd, orchestrator=orch, agent=agent)
        if prompt:
            mark = ORCHESTRATOR_MARK if orch else AGENT_PROMPT_MARK
            extras.append(f"[{mark}]\n{prompt}")
        if orch:
            already.add("host-orchestrator")
        steering = load_steering_markdown(cwd)
        if steering:
            extras.append(steering)
        extras.append(CURSOR_RPC_DELTA)
        return extras
    if orch and "host-orchestrator" not in already:
        already.add("host-orchestrator")
        prompt = load_agent_prompt(cwd, orchestrator=True, agent=agent)
        if prompt:
            extras.append(f"[{ORCHESTRATOR_MARK}]\n{prompt}")
    return extras


class UsageTracker:
    """Session occupancy for Crew's context meter.

    Each Crew prompt already carries the current inject. Take the max of
    (this prompt + outputs) so we do not double-count repeated injects.
    """

    def __init__(self, window: int = CONTEXT_WINDOW_TOKENS) -> None:
        self.window = window if window > 0 else CONTEXT_WINDOW_TOKENS
        self.used = 0
        self._turn_output = 0

    def reset(self) -> None:
        self.used = 0
        self._turn_output = 0

    def note_prompt_chars(self, chars: int) -> None:
        self._turn_output = 0
        estimated = estimate_tokens(chars)
        self.used = clamp_used(max(self.used, estimated), self.window)

    def note_output_chars(self, chars: int) -> None:
        if chars <= 0:
            return
        self._turn_output += estimate_tokens(chars)
        self.used = clamp_used(self.used + estimate_tokens(chars), self.window)

    def note_cursor_used(self, used: int | None) -> None:
        if used is None or used <= 0:
            return
        self.used = clamp_used(max(self.used, used), self.window)

    def snapshot(self) -> tuple[int, int]:
        return self.used, self.window
