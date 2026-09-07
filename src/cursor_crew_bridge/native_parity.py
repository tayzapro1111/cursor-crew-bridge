"""Parity with native Kiro Crew (Fable 5.1) that Cursor ACP does not emit.

Native kiro-cli:
- loads prompt-orchestrator.md on the first turn of an orchestrator slot
- streams usage_update {used, size} or _kiro.dev/metadata.contextUsagePercentage
- session/load restores {sid}.json; on miss, Crew session/new + conversation_log replay

Cursor Agent:
- never sends usage_update (Crew meter stays 0%)
- has no kiro session file (a fake successful load marks RESUMED and skips replay)
- ignores Autopilot if the slot was not new when mode flipped

This module is the shim's stand-in for those three native signals.
"""

from __future__ import annotations

import re
from typing import Any

from cursor_crew_bridge.config import CONTEXT_WINDOW_TOKENS, is_lite_agent

_BACKTICK_PATH_RE = re.compile(r"`([^`]+)`")
_EDIT_PREFIX_RE = re.compile(r"^Edit(?:ing)?\s+", re.IGNORECASE)
_TOOL_SESSION_UPDATES = frozenset({"tool_call", "tool_call_update"})
_PATH_KEYS = ("path", "file_path", "filePath")

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

PLANNING_STEER = f"""[KIRO CREW AUTOPILOT — native Fable contract]
This slot is Autopilot (orchestrator). Crew injects prompt-orchestrator.md only on
a NEW session. Mid-chat Autopilot has no system prompt — this block IS that contract.
Crew parses your assistant TEXT, not Cursor RPCs and not your intent.

Planning turn (no "Execute Stage N of M now"):
1. Read the source first when the task touches a codebase. Scope the plan from
   evidence, not from a shallow guess. A little research BEFORE the plan is fine.
2. Do not give an "easy" direct answer. An Autopilot / explicit plan request
   ALWAYS wins: emit the plan even if the work looks small (2–3 focused stages).
3. Emit exactly this shape, then STOP. No tools after the footer. No implementation.
{PLAN_TEMPLATE}
4. Stages sequential from 1. Each stage is one independently verifiable unit.
   Prefer more focused stages over cramming. Last stage MUST be Verification
   (tests, browser, or the closest evidence — not a rubber stamp).
5. Footer once, last line, singular OPTION not OPTIONS. Nothing after it.
6. Do NOT call cursor/create_plan (accepted and dropped — Crew never sees it).
   cursor/update_todos may update Crew's sidebar; it is not Go. Autopilot UI
   is only {PLAN_FOOTER}.
7. Go / Go All / Cancel are Crew buttons. _stage_loop injects
   "Execute Stage N of M now" as a hidden user message. Do not start Stage 1 here.

Stage turn (message contains "Execute Stage N of M now"):
- Do only that stage, to the depth the bullets require. Write stage_N_result.md.
- End with "✅ Stage N complete". Do not re-emit {PLAN_FOOTER}. Do not re-plan.
"""

STAGE_STEER = f"""[KIRO CREW AUTOPILOT — stage execution]
This message is an auto-go inject from _stage_loop. The plan is already approved.
Do ONLY the current stage — the whole stage, not a light pass.
- Source first. Finish the bullets. Verify claims with tools from this turn.
- If this stage is Verification: actually run tests / exercise the UI / show
  evidence. Do not rubber-stamp.
- Write stage_N_result.md. End with "✅ Stage N complete".
- Do not re-plan. Do not emit {PLAN_FOOTER}. Do not start the next stage.
- In-scope forks: pick the thorough option and continue. Ask only if blocked
  (credentials, destructive, 3 failed attempts, irreconcilable evidence).
"""

BROWSER_STEER = """[KIRO CREW BROWSER]
PRIMARY: MCP kirocrew-core tool `browser` (op=navigate|snapshot|click|type|press_key).
That is the dashboard Browser panel. Do not `execute` playwright-cli / npx playwright
when that MCP tool exists. Playwright CLI is fallback only if browser MCP is absent.
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


def usage_update_message(session_id: str, used: int, size: int = CONTEXT_WINDOW_TOKENS) -> dict[str, Any]:
    window = size if size > 0 else CONTEXT_WINDOW_TOKENS
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

    window = size if size > 0 else CONTEXT_WINDOW_TOKENS
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


def steering_texts(params: dict[str, Any], *, agent: str, crew_mode: str, already: set[str]) -> list[str]:
    """Fable contracts on every Autopilot turn. Lite/optimizer stay unsteered.

    Plan/stage steers are re-sent each matching turn (native ``prompt-orchestrator.md``
    stays in the system prompt for the session). Browser steer stays once.
    """

    if is_lite_agent(agent):
        return []
    text = prompt_text(params)
    extras: list[str] = []
    if "browser" not in already:
        extras.append(BROWSER_STEER)
    if is_stage_execution(text):
        extras.append(STAGE_STEER)
        return extras
    if looks_like_orchestrator(text, crew_mode):
        extras.append(PLANNING_STEER)
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
