"""JSON-RPC ACP translator: Kiro Crew client dialect ↔ Cursor Agent CLI."""

from __future__ import annotations

import asyncio
import json
import sys
import time
import traceback
from typing import Any

from cursor_crew_bridge.agent_mcp import mcp_servers_for_acp, merge_mcp_servers
from cursor_crew_bridge.config import (
    BRIDGE_VERSION,
    CONTEXT_WINDOW_TOKENS,
    DEFAULT_AGENT_NAME,
    DEFAULT_MODEL,
    LITE_MODEL,
    TRACE_DEFAULT,
    advertised_model_aliases,
    is_lite_agent,
    log_paths,
    resolve_cursor_model,
    skip_mcp,
)
from cursor_crew_bridge.cursor_auth import child_env
from cursor_crew_bridge.cursor_cli import acp_argv, redacted_argv
from cursor_crew_bridge.native_parity import (
    ADVERTISE_LOAD_SESSION,
    UsageTracker,
    cursor_prompt_used_tokens,
    cursor_todos_crew_messages,
    drop_update_after_cancel,
    enrich_cursor_tool_update,
    metadata_percentage_message,
    prepend_prompt_blocks,
    prompt_cancelled_result,
    prompt_text,
    remember_orchestrator,
    session_cancel_notification,
    session_load_error,
    steering_texts,
    usage_update_message,
)
from cursor_crew_bridge.workspace import prepare_cwd

KIRO_PROTOCOL = "2025-08-22"
CURSOR_PROTOCOL = 1
CURSOR_ASK = "cursor/ask_question"
CURSOR_PLAN = "cursor/create_plan"
CURSOR_TODOS = "cursor/update_todos"
CURSOR_TASK = "cursor/task"
CURSOR_IMAGE = "cursor/generate_image"
DROP_UPDATES = {
    "available_commands_update",
    "current_mode_update",
    "session_info_update",
}


def _update_kind(msg: dict[str, Any]) -> str:
    params = msg.get("params") if isinstance(msg.get("params"), dict) else {}
    update = params.get("update") if isinstance(params.get("update"), dict) else params
    if isinstance(update, dict):
        return str(update.get("sessionUpdate") or "")
    return ""


def _permission_allow(options: list[Any]) -> dict[str, Any]:
    for option in options:
        if not isinstance(option, dict):
            continue
        oid = str(option.get("optionId") or option.get("id") or "")
        kind = str(option.get("kind") or "").replace("-", "_")
        if "allow" in oid.replace("-", "_") or kind.startswith("allow"):
            return {"outcome": {"outcome": "selected", "optionId": oid or "allow-once"}}
    if options and isinstance(options[0], dict):
        oid = str(options[0].get("optionId") or options[0].get("id") or "allow-once")
        return {"outcome": {"outcome": "selected", "optionId": oid}}
    return {"outcome": {"outcome": "selected", "optionId": "allow-once"}}

MODE_MAP = {
    "kirocrew": "agent",
    "kirocrew-conductor": "plan",
    "kirocrew-heartbeat": "agent",
    "kirocrew-knowledge": "agent",
    "kirocrew-research": "agent",
    "kirocrew-lite": "ask",
    "spec": "agent",
    "ask": "ask",
    "plan": "plan",
    "agent": "agent",
    "default": "agent",
    "orchestrator": "agent",
    "autopilot": "agent",
}


def _log(message: str) -> None:
    # Never write Crew's JSON-RPC stderr pipe: on Windows the unread stderr
    # buffer deadlocks kiro-cli and Crew then reaps us with rc=1.
    stamp = time.strftime("%Y-%m-%dT%H:%M:%S")
    line = f"{stamp} {message.rstrip()}\n"
    for target in log_paths():
        try:
            with target.open("a", encoding="utf-8") as handle:
                handle.write(line)
        except OSError:
            continue


# Flow-control only. Lines themselves are assembled in `_LineBuf` with no cap.
ACP_STREAM_LIMIT = 1024 * 1024
# Crew's ACP client drops JSON-RPC lines over 10 MiB and then waits forever
# for the prompt result. Stay under that when writing to Crew.
CREW_LINE_MAX = 8 * 1024 * 1024
CREW_TEXT_CHUNK = 700_000
# Images must stay intact (truncated base64 is corrupt). Crew still hard-drops
# at 10 MiB, so vision frames get a slightly higher budget than text.
CREW_HARD_MAX = 10 * 1024 * 1024 - 64 * 1024


def _dumps(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")


class _LineBuf:
    """Newline-framed ACP reader that never raises LimitOverrunError."""

    def __init__(self, reader: asyncio.StreamReader, chunk: int = ACP_STREAM_LIMIT) -> None:
        self._reader = reader
        self._buf = bytearray()
        self._chunk = chunk

    async def readline(self) -> bytes:
        while True:
            nl = self._buf.find(b"\n")
            if nl >= 0:
                line = bytes(self._buf[: nl + 1])
                del self._buf[: nl + 1]
                return line
            piece = await self._reader.read(self._chunk)
            if not piece:
                if self._buf:
                    line = bytes(self._buf)
                    self._buf.clear()
                    return line
                return b""
            self._buf.extend(piece)


def _clone_update(msg: dict[str, Any], text: str) -> dict[str, Any]:
    params = msg.get("params") if isinstance(msg.get("params"), dict) else {}
    update = params.get("update") if isinstance(params.get("update"), dict) else dict(params)
    content = update.get("content") if isinstance(update.get("content"), dict) else {}
    new_content = dict(content)
    new_content["text"] = text
    new_update = dict(update)
    new_update["content"] = new_content
    new_params = dict(params)
    new_params["update"] = new_update
    out = dict(msg)
    out["params"] = new_params
    return out


def _contains_image(value: Any) -> bool:
    if isinstance(value, dict):
        kind = str(value.get("type") or "").lower()
        if kind == "image" or "mimeType" in value:
            return True
        return any(_contains_image(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_image(item) for item in value)
    return False


def _image_placeholder(msg: dict[str, Any], text: str) -> dict[str, Any]:
    params = msg.get("params") if isinstance(msg.get("params"), dict) else {}
    return {
        "jsonrpc": "2.0",
        "method": "session/update",
        "params": {
            "sessionId": params.get("sessionId"),
            "update": {
                "sessionUpdate": "agent_message_chunk",
                "content": {"type": "text", "text": text},
            },
        },
    }


def _split_update_text(msg: dict[str, Any]) -> list[dict[str, Any]] | None:
    if msg.get("method") != "session/update":
        return None
    params = msg.get("params") if isinstance(msg.get("params"), dict) else {}
    update = params.get("update") if isinstance(params.get("update"), dict) else params
    if not isinstance(update, dict):
        return None
    content = update.get("content")
    if not isinstance(content, dict):
        return None
    text = content.get("text")
    if not isinstance(text, str) or len(text) <= CREW_TEXT_CHUNK:
        return None
    return [_clone_update(msg, text[i : i + CREW_TEXT_CHUNK]) for i in range(0, len(text), CREW_TEXT_CHUNK)]


def _shrink_strings(value: Any, cap: int, *, keep: bool = False) -> Any:
    if isinstance(value, dict):
        image = str(value.get("type") or "").lower() == "image" or "mimeType" in value
        return {
            k: _shrink_strings(v, cap, keep=image or k in {"data", "mimeType", "blob"})
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_shrink_strings(v, cap, keep=keep) for v in value]
    if keep:
        return value
    if isinstance(value, str) and len(value) > cap:
        omitted = len(value) - cap
        return value[:cap] + f"\n…[cursor-crew-bridge truncated {omitted} chars]\n"
    return value


def crew_outbound_messages(msg: dict[str, Any]) -> list[dict[str, Any]]:
    """Frames Crew can actually parse. Never drop a prompt result on the floor."""

    raw = _dumps(msg)
    if _contains_image(msg):
        if len(raw) <= CREW_HARD_MAX:
            return [msg]
        _log("image ACP frame exceeds Crew's 10MB line; sending placeholder")
        return [_image_placeholder(msg, "[cursor-crew-bridge: image too large for Crew's 10MB ACP line]")]
    if len(raw) <= CREW_LINE_MAX:
        return [msg]
    split = _split_update_text(msg)
    if split and all(len(_dumps(item)) <= CREW_LINE_MAX for item in split):
        _log(f"split session/update into {len(split)} crew frames")
        return split
    cap = CREW_TEXT_CHUNK
    shrunk = msg
    for _ in range(8):
        shrunk = _shrink_strings(shrunk, cap)
        if len(_dumps(shrunk)) <= CREW_LINE_MAX:
            _log(f"shrunk oversized ACP frame for Crew (cap={cap})")
            return [shrunk]
        cap = max(8000, cap // 2)
    _log("ACP frame still oversized after shrink; sending stub")
    stub = dict(msg)
    if "result" in stub:
        stub["result"] = {"stopReason": "end_turn"}
    elif stub.get("method") == "session/update":
        stub = _clone_update(msg, "[cursor-crew-bridge: tool output too large for Crew's 10MB ACP line]")
    return [stub]


async def _readline_bounded(reader: asyncio.StreamReader) -> bytes:
    """Back-compat wrapper used by tests; prefers unlimited `_LineBuf`."""

    return await _LineBuf(reader).readline()


def _parse_line(raw: bytes) -> dict[str, Any] | None:
    text = raw.decode("utf-8", "replace").strip()
    if not text:
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        _log(f"skip non-json: {text[:200]}")
        return None
    return data if isinstance(data, dict) else None


def _rewrite_model(model_id: Any) -> str:
    if not isinstance(model_id, str):
        return DEFAULT_MODEL
    return resolve_cursor_model(model_id, lite=False)


def _prompt_chars(params: dict[str, Any]) -> int:
    prompt = params.get("prompt")
    total = 0
    if isinstance(prompt, list):
        for block in prompt:
            if isinstance(block, str):
                total += len(block)
            elif isinstance(block, dict) and isinstance(block.get("text"), str):
                total += len(block["text"])
    elif isinstance(prompt, str):
        total = len(prompt)
    return total


def _trace_cursor_update(msg: dict[str, Any]) -> None:
    if not TRACE_DEFAULT:
        return
    kind = _update_kind(msg)
    params = msg.get("params") if isinstance(msg.get("params"), dict) else {}
    update = params.get("update") if isinstance(params.get("update"), dict) else params
    if not isinstance(update, dict):
        _log(f"cursor← {msg.get('method')}")
        return
    if kind in {"tool_call", "tool_call_update"}:
        _log(
            f"cursor← {kind} tool={update.get('kind')} status={update.get('status')} "
            f"title={str(update.get('title') or '')[:120]!r} id={update.get('toolCallId')}"
        )
        return
    if kind in {"agent_thought_chunk", "agent_message_chunk"}:
        content = update.get("content") if isinstance(update.get("content"), dict) else {}
        text = content.get("text") if isinstance(content.get("text"), str) else ""
        preview = text[:160].replace("\n", " ")
        _log(f"cursor← {kind} +{len(text)} {preview!r}")
        return
    _log(f"cursor← {kind or msg.get('method')}")


def _model_entry(model_id: str, name: str) -> dict[str, str | int]:
    return {
        "id": model_id,
        "modelId": model_id,
        "value": model_id,
        "name": name,
        "description": name,
        "contextWindow": CONTEXT_WINDOW_TOKENS,
        "contextWindowTokens": CONTEXT_WINDOW_TOKENS,
        "context_window_tokens": CONTEXT_WINDOW_TOKENS,
    }


def _inject_modes(result: dict[str, Any], agent: str) -> dict[str, Any]:
    mode_id = agent or DEFAULT_AGENT_NAME
    advertised = [
        {"id": mode_id, "name": mode_id, "description": "Cursor Grok via crew bridge"},
        {"id": "agent", "name": "agent", "description": "Cursor agent mode"},
        {"id": "plan", "name": "plan", "description": "Cursor plan mode"},
        {"id": "ask", "name": "ask", "description": "Cursor ask mode"},
    ]
    seen = {item["id"] for item in advertised}
    for extra in ("kirocrew", "kirocrew-conductor", "kirocrew-lite"):
        if extra not in seen:
            advertised.append({"id": extra, "name": extra, "description": extra})
    result["modes"] = {"currentModeId": mode_id, "availableModes": advertised}
    # Crew entitlement checks `modelId`, not `id`. Cursor's native list uses
    # tagged ids like `claude-opus-5[thinking=true…]`; if we forward that list,
    # Crew withholds `auto`→opus and then races a second set_model. Pin only Grok.
    result["models"] = {
        "currentModelId": DEFAULT_MODEL,
        "availableModels": [_model_entry(model_id, name) for model_id, name in advertised_model_aliases()],
    }
    return result


def _clamp_token_size(value: Any) -> Any:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return value
    if value > CONTEXT_WINDOW_TOKENS:
        return CONTEXT_WINDOW_TOKENS
    return value


def _clamp_usage_update(msg: dict[str, Any]) -> dict[str, Any]:
    """Cursor may advertise a 1M window. Extra High is 256k — Crew's meter and
    autocompact (70% of ``size``) must use the real cap, or Grok dies first."""

    if msg.get("method") != "session/update":
        return msg
    params = msg.get("params")
    if not isinstance(params, dict):
        return msg
    update = params.get("update") if isinstance(params.get("update"), dict) else None
    if not isinstance(update, dict):
        return msg
    if str(update.get("sessionUpdate") or "") != "usage_update":
        return msg
    new_update = dict(update)
    nested = new_update.get("usage")
    if isinstance(nested, dict):
        new_update["usage"] = dict(nested)
        nested = new_update["usage"]
    else:
        nested = None
    changed = False
    for container in (new_update, nested):
        if not isinstance(container, dict):
            continue
        size = container.get("size")
        clamped = _clamp_token_size(size)
        if clamped != size:
            container["size"] = clamped
            changed = True
        used = container.get("used")
        size_now = container.get("size")
        if (
            isinstance(used, (int, float))
            and not isinstance(used, bool)
            and (size_now is None or (isinstance(size_now, (int, float)) and not isinstance(size_now, bool) and size_now <= 0))
        ):
            container["size"] = CONTEXT_WINDOW_TOKENS
            changed = True
    if not changed:
        return msg
    out = dict(msg)
    new_params = dict(params)
    new_params["update"] = new_update
    out["params"] = new_params
    return out


def _apply_tool_title_enrichment(msg: dict[str, Any]) -> dict[str, Any]:
    if msg.get("method") != "session/update":
        return msg
    params = msg.get("params")
    if not isinstance(params, dict):
        return msg
    update = params.get("update")
    if not isinstance(update, dict):
        return msg
    enriched = enrich_cursor_tool_update(update)
    if enriched is update:
        return msg
    out = dict(msg)
    new_params = dict(params)
    new_params["update"] = enriched
    out["params"] = new_params
    return out


def _normalize_update(msg: dict[str, Any]) -> dict[str, Any]:
    if msg.get("method") != "session/update":
        return msg
    params = msg.get("params")
    if not isinstance(params, dict):
        return msg
    if isinstance(params.get("update"), dict):
        return _apply_tool_title_enrichment(_clamp_usage_update(msg))
    if "sessionUpdate" in params:
        session_id = params.get("sessionId")
        update = {k: v for k, v in params.items() if k != "sessionId"}
        wrapped = dict(msg)
        wrapped["params"] = {"sessionId": session_id, "update": update}
        return _apply_tool_title_enrichment(_clamp_usage_update(wrapped))
    return msg


def _rewrite_permission_options(msg: dict[str, Any]) -> dict[str, Any]:
    params = msg.get("params")
    if not isinstance(params, dict):
        return msg
    options = params.get("options")
    if not isinstance(options, list):
        return msg
    rewritten = []
    for option in options:
        if not isinstance(option, dict):
            continue
        item = dict(option)
        opt_id = str(item.get("optionId") or item.get("id") or "")
        kind = str(item.get("kind") or "")
        if opt_id in {"allow-once", "allow_once", "allow"} and not kind:
            item["kind"] = "allow_once"
        if opt_id in {"allow-always", "allow_always"} and not kind:
            item["kind"] = "allow_always"
        if opt_id in {"reject-once", "reject_once", "reject"} and not kind:
            item["kind"] = "reject_once"
        rewritten.append(item)
    out = dict(msg)
    new_params = dict(params)
    new_params["options"] = rewritten
    out["params"] = new_params
    return out


def _map_permission_result(result: Any, advertised: list[dict[str, Any]] | None) -> Any:
    if not isinstance(result, dict):
        return result
    outcome = result.get("outcome")
    if not isinstance(outcome, dict):
        return result
    option_id = outcome.get("optionId")
    if not isinstance(option_id, str):
        return result
    allow_ids = []
    reject_ids = []
    for option in advertised or []:
        if not isinstance(option, dict):
            continue
        oid = str(option.get("optionId") or option.get("id") or "")
        kind = str(option.get("kind") or "").replace("-", "_")
        if kind.startswith("allow") or oid.replace("-", "_") in {"allow_once", "allow_always", "allow"}:
            allow_ids.append(oid)
        if kind.startswith("reject") or "reject" in oid.replace("-", "_"):
            reject_ids.append(oid)
    mapped = dict(result)
    new_outcome = dict(outcome)
    wanted = option_id.replace("-", "_")
    if wanted in {"allow_once", "allow_always", "allow"} and allow_ids:
        new_outcome["optionId"] = allow_ids[0]
    elif "reject" in wanted and reject_ids:
        new_outcome["optionId"] = reject_ids[0]
    mapped["outcome"] = new_outcome
    return mapped


def _ask_question_text(params: dict[str, Any]) -> str:
    questions = params.get("questions") if isinstance(params.get("questions"), list) else []
    lines: list[str] = []
    for question in questions:
        if not isinstance(question, dict):
            continue
        prompt = str(question.get("prompt") or question.get("question") or "").strip()
        if prompt:
            lines.append(prompt)
        options = question.get("options") if isinstance(question.get("options"), list) else []
        for option in options:
            if not isinstance(option, dict):
                continue
            label = str(option.get("label") or option.get("id") or "").strip()
            if label:
                lines.append(f"- {label}")
    return "\n".join(lines)


def _ask_question_result(_params: dict[str, Any]) -> dict[str, Any]:
    # Do not pick the first option. Native Crew shows a card; Cursor ACP cannot
    # render one here, so skip and surface the question as chat text instead.
    return {"outcome": {"outcome": "skipped", "reason": "shown in chat; not auto-answered"}}


def _extract_image_block(value: Any) -> dict[str, str] | None:
    if not isinstance(value, dict):
        return None
    kind = str(value.get("type") or "").lower()
    mime = value.get("mimeType") or value.get("mime")
    data = value.get("data") or value.get("imageData") or value.get("blob")
    if isinstance(data, str) and data and (kind == "image" or isinstance(mime, str) and mime.startswith("image/")):
        return {"type": "image", "data": data, "mimeType": str(mime or "image/png")}
    for item in value.values():
        found = _extract_image_block(item)
        if found:
            return found
        if isinstance(item, list):
            for nested in item:
                found = _extract_image_block(nested)
                if found:
                    return found
    return None


class AcpBridge:
    def __init__(self, agent: str) -> None:
        self.agent = agent or DEFAULT_AGENT_NAME
        self.proc: asyncio.subprocess.Process | None = None
        self._auth_done = False
        self._pending_permissions: dict[Any, list[dict[str, Any]]] = {}
        self._held_init: dict[str, Any] | None = None
        self._auth_req_id = "bridge-auth"
        self._pending_methods: dict[Any, str] = {}
        self._cursor_lock = asyncio.Lock()
        self._bridge_rpc = 900000
        self._stdout_lines: _LineBuf | None = None
        self._stderr_lines: _LineBuf | None = None
        self._session_id: str | None = None
        self._fatal: str | None = None
        self._crew_mode = ""
        self._steered: set[str] = set()
        self._usage = UsageTracker()
        self._prompt_req_id: Any = None
        self._turn_cancelled = False
        self._answered_prompt_ids: set[Any] = set()
        self._cancel_watch: asyncio.Task[None] | None = None

    def _next_bridge_id(self) -> int:
        self._bridge_rpc += 1
        return self._bridge_rpc

    def _spawn_model(self) -> str:
        if is_lite_agent(self.agent):
            return resolve_cursor_model(LITE_MODEL, lite=True)
        return resolve_cursor_model(DEFAULT_MODEL, lite=False)

    def _track_forward(self, req_id: Any, method: str) -> None:
        if req_id is not None:
            self._pending_methods[req_id] = method

    def _output_chars(self, msg: dict[str, Any]) -> int:
        if _update_kind(msg) not in {"agent_thought_chunk", "agent_message_chunk"}:
            return 0
        params = msg.get("params") if isinstance(msg.get("params"), dict) else {}
        update = params.get("update") if isinstance(params.get("update"), dict) else params
        if not isinstance(update, dict):
            return 0
        content = update.get("content") if isinstance(update.get("content"), dict) else {}
        text = content.get("text") if isinstance(content.get("text"), str) else ""
        return len(text)

    async def _emit_usage(self, session_id: str | None = None) -> None:
        sid = (session_id or "").strip() or self._session_id
        if sid and sid != self._session_id:
            self._session_id = sid
        if not sid:
            return
        used, window = self._usage.snapshot()
        if used <= 0:
            return
        await self._send_crew(usage_update_message(sid, used, window))
        await self._send_crew(metadata_percentage_message(sid, used, window))
        _log(f"usage used={used} window={window} pct={round(used / window * 100, 1) if window else 0}")

    async def _fail_open_crew_rpcs(self, reason: str) -> None:
        pending = dict(self._pending_methods)
        self._pending_methods.clear()
        _log(f"FAIL open crew RPCs ({len(pending)}): {reason}")
        for req_id, method in pending.items():
            await self._send_crew(
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32000, "message": f"cursor-crew-bridge: {reason} ({method})"},
                }
            )

    async def start(self) -> None:
        extra: list[str] = []
        mapped = MODE_MAP.get(self.agent, "agent")
        if mapped in {"ask", "plan"}:
            extra.extend(["--mode", mapped])
        model = self._spawn_model()
        argv = acp_argv(model=model, extra=extra)
        _log(
            f"spawn agent={self.agent} model={model} lite={is_lite_agent(self.agent)} "
            f"argv={redacted_argv(argv)!r}"
        )
        self.proc = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=child_env(),
            limit=ACP_STREAM_LIMIT,
        )
        if self.proc.pid:
            try:
                from cursor_crew_bridge.winjob import attach_kill_on_close

                if attach_kill_on_close(self.proc.pid):
                    _log(f"cursor pid {self.proc.pid} attached to kill-on-close job")
                else:
                    _log(f"cursor pid {self.proc.pid} job attach skipped (already in a job?)")
            except Exception:
                _log("winjob attach failed:\n" + traceback.format_exc())
        if self.proc.stdout:
            self._stdout_lines = _LineBuf(self.proc.stdout)
        if self.proc.stderr:
            self._stderr_lines = _LineBuf(self.proc.stderr)
        asyncio.create_task(self._pump_stderr())

    async def _pump_stderr(self) -> None:
        reader = self._stderr_lines
        if reader is None:
            return
        while True:
            line = await reader.readline()
            if not line:
                return
            if line in {b"\n", b"\r\n"}:
                continue
            text = line.decode("utf-8", "replace").rstrip()
            if len(text) > 4000:
                text = text[:4000] + f"…(+{len(text) - 4000} chars)"
            _log("cursor-stderr: " + text)
            lowered = text.lower()
            if "cannot use this model" in lowered or "unknown model" in lowered:
                self._fatal = text
                _log(f"FATAL model rejected — killing Cursor ACP: {text[:240]}")
                if self.proc and self.proc.returncode is None:
                    try:
                        self.proc.kill()
                    except OSError:
                        pass

    async def _send_cursor(self, payload: dict[str, Any]) -> None:
        if not (self.proc and self.proc.stdin):
            _log(f"cursor stdin missing while sending {payload.get('method') or payload.get('id')}")
            return
        async with self._cursor_lock:
            try:
                self.proc.stdin.write(_dumps(payload))
                await self.proc.stdin.drain()
            except (BrokenPipeError, ConnectionResetError, OSError) as exc:
                _log(f"cursor stdin closed while sending {payload.get('method') or payload.get('id')}: {exc}")
                return

    async def _send_crew(self, payload: dict[str, Any]) -> None:
        try:
            for frame in crew_outbound_messages(payload):
                sys.stdout.buffer.write(_dumps(frame))
            sys.stdout.buffer.flush()
        except OSError as exc:
            _log(f"crew stdout closed while sending {payload.get('method') or payload.get('id')}: {exc}")

    def _clear_cancel_watch(self) -> None:
        watch = self._cancel_watch
        self._cancel_watch = None
        if watch and not watch.done():
            watch.cancel()

    async def _cancel_watchdog(self) -> None:
        try:
            await asyncio.sleep(6)
        except asyncio.CancelledError:
            return
        req_id = self._prompt_req_id
        if not self._turn_cancelled or req_id is None or req_id in self._answered_prompt_ids:
            return
        _log(f"cancel watchdog: synthesize prompt cancelled id={req_id}")
        self._answered_prompt_ids.add(req_id)
        self._pending_methods.pop(req_id, None)
        self._prompt_req_id = None
        await self._send_crew(prompt_cancelled_result(req_id))

    async def _cancel_turn(self, params: dict[str, Any]) -> None:
        sid = params.get("sessionId") if isinstance(params.get("sessionId"), str) else self._session_id
        self._turn_cancelled = True
        _log(f"session/cancel notification sid={sid} prompt_id={self._prompt_req_id}")
        if sid:
            await self._send_cursor(session_cancel_notification(sid))
        self._clear_cancel_watch()
        if self._prompt_req_id is not None:
            self._cancel_watch = asyncio.create_task(self._cancel_watchdog())

    async def _terminate_session(self, req_id: Any, params: dict[str, Any]) -> None:
        sid = params.get("sessionId") if isinstance(params.get("sessionId"), str) else self._session_id
        _log(f"terminate session sid={sid}")
        if sid and self.proc and self.proc.returncode is None:
            await self._send_cursor(session_cancel_notification(sid))
        if req_id is not None:
            await self._send_crew({"jsonrpc": "2.0", "id": req_id, "result": {}})
        self._clear_cancel_watch()
        self._prompt_req_id = None
        self._turn_cancelled = False
        self._session_id = None

    async def _forward_generated_image(self, msg: dict[str, Any]) -> None:
        params = msg.get("params") if isinstance(msg.get("params"), dict) else {}
        image = _extract_image_block(params)
        if not image:
            return
        sid = params.get("sessionId") if isinstance(params.get("sessionId"), str) else self._session_id
        if not sid:
            return
        await self._send_crew(
            {
                "jsonrpc": "2.0",
                "method": "session/update",
                "params": {
                    "sessionId": sid,
                    "update": {"sessionUpdate": "agent_message_chunk", "content": image},
                },
            }
        )

    async def _handle_cursor_message(self, msg: dict[str, Any]) -> None:
        method = msg.get("method")
        if method in {CURSOR_ASK, CURSOR_PLAN} and msg.get("id") is not None:
            params = msg.get("params") if isinstance(msg.get("params"), dict) else {}
            if method == CURSOR_ASK:
                result = _ask_question_result(params)
                text = _ask_question_text(params)
                if text:
                    sid = params.get("sessionId") if isinstance(params.get("sessionId"), str) else self._session_id
                    if sid:
                        await self._send_crew(
                            {
                                "jsonrpc": "2.0",
                                "method": "session/update",
                                "params": {
                                    "sessionId": sid,
                                    "update": {
                                        "sessionUpdate": "agent_message_chunk",
                                        "content": {"type": "text", "text": text + "\n"},
                                    },
                                },
                            }
                        )
            else:
                # cursor/create_plan is Cursor's plan UI. Crew's Autopilot
                # parser only accepts 📋 / Stage N: / [OPTION: Go | Go All | Cancel]
                # in assistant text. Mapping this RPC would race: Cursor treats
                # accepted as "user approved, start work" while Crew still
                # waits on Go. Keep accepted so the RPC does not hang; drop
                # the body. PLANNING_STEER forbids the call.
                result = {"outcome": {"outcome": "accepted"}}
            await self._send_cursor({"jsonrpc": "2.0", "id": msg["id"], "result": result})
            return
        if method in {CURSOR_TODOS, CURSOR_TASK}:
            params = msg.get("params") if isinstance(msg.get("params"), dict) else {}
            sid = params.get("sessionId") if isinstance(params.get("sessionId"), str) else self._session_id
            if method == CURSOR_TODOS and sid and not self._turn_cancelled:
                for frame in cursor_todos_crew_messages(sid, params):
                    await self._send_crew(frame)
            if msg.get("id") is not None:
                await self._send_cursor({"jsonrpc": "2.0", "id": msg["id"], "result": {"outcome": {"outcome": "accepted"}}})
            return
        if method == CURSOR_IMAGE:
            if msg.get("id") is not None:
                await self._send_cursor({"jsonrpc": "2.0", "id": msg["id"], "result": {"outcome": {"outcome": "accepted"}}})
            await self._forward_generated_image(msg)
            return
        if method == "session/request_permission":
            params = msg.get("params") if isinstance(msg.get("params"), dict) else {}
            options = params.get("options") if isinstance(params.get("options"), list) else []
            result = _permission_allow(options)
            _log(f"auto-allow permission {result}")
            await self._send_cursor({"jsonrpc": "2.0", "id": msg["id"], "result": result})
            return
        if method == "session/update":
            _trace_cursor_update(msg)
            out_chars = self._output_chars(msg)
            if out_chars:
                self._usage.note_output_chars(out_chars)
        if method == "session/update" and _update_kind(msg) in DROP_UPDATES:
            return
        if method == "session/update" and self._turn_cancelled and drop_update_after_cancel(_update_kind(msg)):
            return
        # Cursor-only RPCs hang Crew. Real client methods (fs/terminal) must
        # reach Crew or photos/tools that go through ACP client I/O stall.
        if method and msg.get("id") is not None and method != "session/update":
            kind = str(method)
            if kind.startswith("fs/") or kind.startswith("terminal/"):
                await self._send_crew(msg)
                return
            _log(f"auto-reply cursor request {method}")
            await self._send_cursor({"jsonrpc": "2.0", "id": msg["id"], "result": {}})
            return
        await self._send_crew(_normalize_update(msg))

    def _auth_required(self, init_result: dict[str, Any]) -> bool:
        methods = init_result.get("authMethods") or init_result.get("authenticationMethods") or []
        if not isinstance(methods, list):
            return False
        for item in methods:
            if item == "cursor_login":
                return True
            if isinstance(item, dict) and item.get("id") in {"cursor_login", "cursor"}:
                return True
        return False

    async def _kickoff_authenticate(self) -> None:
        await self._send_cursor(
            {
                "jsonrpc": "2.0",
                "id": self._auth_req_id,
                "method": "authenticate",
                "params": {"methodId": "cursor_login"},
            }
        )

    async def _handle_crew_request(self, msg: dict[str, Any]) -> None:
        method = msg.get("method")
        req_id = msg.get("id")
        params = msg.get("params") if isinstance(msg.get("params"), dict) else {}
        if TRACE_DEFAULT:
            extra = ""
            if method == "session/prompt":
                extra = f" chars={_prompt_chars(params)}"
            _log(f"crew→ {method} id={req_id}{extra}")

        if method == "initialize":
            crew_caps = params.get("clientCapabilities") if isinstance(params.get("clientCapabilities"), dict) else {}
            fs = crew_caps.get("fs") if isinstance(crew_caps.get("fs"), dict) else {}
            # Crew does not serve ACP fs/terminal. Advertising true makes Cursor
            # call methods Crew answers with -32601. Pass the real caps through.
            forwarded_caps: dict[str, Any] = {
                "fs": {
                    "readTextFile": bool(fs.get("readTextFile")),
                    "writeTextFile": bool(fs.get("writeTextFile")),
                },
                "terminal": bool(crew_caps.get("terminal")),
            }
            forwarded = {
                "jsonrpc": "2.0",
                "id": req_id,
                "method": "initialize",
                "params": {
                    "protocolVersion": CURSOR_PROTOCOL,
                    "clientInfo": {"name": "kirocrew-cursor-bridge", "version": BRIDGE_VERSION},
                    "clientCapabilities": forwarded_caps,
                },
            }
            self._track_forward(req_id, "initialize")
            await self._send_cursor(forwarded)
            return

        if method == "session/load":
            # Cursor has no kiro {sid}.json. A successful fake load marks the
            # Crew session RESUMED and skips conversation_log replay — Grok
            # starts empty while the UI still shows the transcript. Fail like a
            # missing native file so Crew does session/new + FirstTurnState.FRESH.
            _log("session/load refused — Crew must session/new and replay history")
            if req_id is not None:
                await self._send_crew(
                    {"jsonrpc": "2.0", "id": req_id, "error": session_load_error()}
                )
            return

        if method == "session/new":
            cwd = prepare_cwd(str(params.get("cwd") or params.get("Cwd") or ""))
            incoming = params.get("mcpServers") if isinstance(params.get("mcpServers"), list) else []
            # Lite/optimizer must stay mcp=0. Merging the 14-server kirocrew
            # roster onto a cold start is what made the first Optimize Prompt
            # press sit for 30s and then reset.
            if skip_mcp() or is_lite_agent(self.agent):
                unique: list[dict[str, Any]] = []
            else:
                unique = merge_mcp_servers(incoming, mcp_servers_for_acp(self.agent))
            _log(
                f"{method} cwd={cwd} mcp={len(unique)} skip={skip_mcp()} "
                f"lite={is_lite_agent(self.agent)}"
            )
            self._usage.reset()
            self._steered.clear()
            self._crew_mode = ""
            self._turn_cancelled = False
            self._prompt_req_id = None
            self._clear_cancel_watch()
            new_params = {"cwd": cwd, "mcpServers": unique}
            self._track_forward(req_id, "session/new")
            await self._send_cursor({"jsonrpc": "2.0", "id": req_id, "method": "session/new", "params": new_params})
            return

        if method == "session/prompt":
            # set_mode is the agent name (kirocrew), never slot.mode=orchestrator.
            self._crew_mode = remember_orchestrator(prompt_text(params), self._crew_mode)
            extras = steering_texts(
                params,
                agent=self.agent,
                crew_mode=self._crew_mode,
                already=self._steered,
            )
            if extras:
                if any("AUTOPILOT — native" in item for item in extras):
                    self._steered.add("plan")
                if any("stage execution" in item for item in extras):
                    self._steered.add("stage")
                if any("KIRO CREW BROWSER" in item for item in extras):
                    self._steered.add("browser")
                params = prepend_prompt_blocks(params, extras)
                _log(f"session/prompt steered={sorted(self._steered)} extra_blocks={len(extras)}")
            chars = _prompt_chars(params)
            self._usage.note_prompt_chars(chars)
            prompt_sid = params.get("sessionId") if isinstance(params.get("sessionId"), str) else None
            forwarded = dict(msg)
            forwarded["params"] = params
            self._turn_cancelled = False
            self._prompt_req_id = req_id
            self._clear_cancel_watch()
            self._track_forward(req_id, "session/prompt")
            await self._send_cursor(forwarded)
            await self._emit_usage(prompt_sid)
            return

        if method == "session/set_mode":
            # Do not forward. Extra RPCs after session/new (set_mode + set_model)
            # exited Cursor ACP with rc=1. Mode is already agent via CLI spawn.
            mode_id = str(params.get("modeId") or "")
            if mode_id.lower() in {"orchestrator", "autopilot"}:
                self._crew_mode = "orchestrator"
            elif mode_id:
                self._crew_mode = mode_id
            mapped = MODE_MAP.get(mode_id, MODE_MAP.get(self.agent, "agent"))
            _log(f"local-ack set_mode {mode_id!r} -> {mapped} crew_mode={self._crew_mode!r}")
            if req_id is not None:
                await self._send_crew({"jsonrpc": "2.0", "id": req_id, "result": {}})
            return

        if method == "session/set_model":
            wanted = params.get("modelId")
            pinned = _rewrite_model(wanted)
            _log(f"local-ack set_model {wanted!r} -> {pinned} (CLI --model already pinned)")
            if req_id is not None:
                await self._send_crew({"jsonrpc": "2.0", "id": req_id, "result": {}})
            return

        if method == "session/set_config_option":
            await self._send_crew({"jsonrpc": "2.0", "id": req_id, "result": {}})
            return

        if method == "session/cancel":
            await self._cancel_turn(params)
            return

        if method == "_kiro.dev/session/terminate":
            await self._terminate_session(req_id, params)
            return

        if method and str(method).startswith("_kiro."):
            _log(f"local-ack {method}")
            result: dict[str, Any] = {}
            if method.endswith("compaction/status") or method.endswith("compaction_status"):
                result = {"status": "idle"}
            if req_id is not None:
                await self._send_crew({"jsonrpc": "2.0", "id": req_id, "result": result})
            return

        if req_id is not None and "result" in msg:
            advertised = self._pending_permissions.pop(req_id, None)
            patched = dict(msg)
            patched["result"] = _map_permission_result(msg.get("result"), advertised)
            await self._send_cursor(patched)
            return

        if req_id is not None and method:
            self._track_forward(req_id, str(method))
        await self._send_cursor(msg)

    async def _release_init(self) -> None:
        held = self._held_init
        self._held_init = None
        if held:
            await self._send_crew(held)

    async def _handle_cursor_response(self, msg: dict[str, Any], crew_waiting_init: set[Any]) -> None:
        tracked = ""
        if msg.get("id") is not None and ("result" in msg or "error" in msg):
            if msg.get("id") != self._auth_req_id:
                tracked = self._pending_methods.pop(msg.get("id"), "")
        if msg.get("id") == self._auth_req_id:
            if msg.get("error"):
                _log(f"authenticate error: {msg['error']}")
            self._auth_done = True
            await self._release_init()
            return
        if msg.get("id") in crew_waiting_init and "result" in msg:
            result = msg.get("result") if isinstance(msg.get("result"), dict) else {}
            crew_result = {
                "jsonrpc": "2.0",
                "id": msg.get("id"),
                "result": {
                    "protocolVersion": KIRO_PROTOCOL,
                    "agentCapabilities": {
                        # Honest: no kiro {sid}.json. True + a successful fake
                        # load marked RESUMED and skipped conversation_log replay.
                        "loadSession": ADVERTISE_LOAD_SESSION,
                        "promptCapabilities": {"image": True, "audio": False, "embeddedContext": False},
                    },
                    "serverInfo": {"name": "cursor-crew-bridge", "version": BRIDGE_VERSION},
                },
            }
            crew_waiting_init.discard(msg.get("id"))
            if self._auth_required(result) and not self._auth_done:
                self._held_init = crew_result
                await self._kickoff_authenticate()
                return
            self._auth_done = True
            await self._send_crew(crew_result)
            return
        if msg.get("id") is not None and "result" in msg:
            result = msg.get("result")
            method = tracked
            # Only rewrite session/new. set_mode/set_model results often contain
            # `modes`/`models`; treating those as session/new used to fire a
            # second overlapping set_model and kill Cursor ACP (rc=1).
            if method == "session/new" and isinstance(result, dict):
                result = _inject_modes(dict(result), self.agent)
                sid = result.get("sessionId")
                if isinstance(sid, str) and sid.strip():
                    self._session_id = sid.strip()
                _log(
                    "session/new "
                    f"sid={result.get('sessionId')} "
                    f"model={self._spawn_model()} "
                    f"window={CONTEXT_WINDOW_TOKENS} "
                    f"mode={self.agent}"
                )
                await self._send_crew({"jsonrpc": "2.0", "id": msg.get("id"), "result": result})
                return
            if method == "session/prompt":
                req_id = msg.get("id")
                if req_id in self._answered_prompt_ids:
                    _log(f"drop late prompt result id={req_id} (already cancelled)")
                    return
                was_cancelled = self._turn_cancelled
                self._answered_prompt_ids.add(req_id)
                self._prompt_req_id = None
                self._turn_cancelled = False
                self._clear_cancel_watch()
                if was_cancelled and isinstance(result, dict):
                    result = dict(result)
                    result["stopReason"] = "cancelled"
                    msg = dict(msg)
                    msg["result"] = result
                self._usage.note_cursor_used(cursor_prompt_used_tokens(result))
                await self._emit_usage()
            if method:
                _log(f"cursor result {method}")
        if msg.get("id") is not None and "error" in msg:
            method = tracked
            method_hint = str((msg.get("error") or {}).get("message") or "")
            if (
                method in {"session/set_mode", "session/set_model", "session/set_config_option"}
                or "not found" in method_hint.lower()
                or (msg.get("error") or {}).get("code") == -32601
            ):
                _log(f"swallow {method or 'rpc'} error: {msg.get('error')}")
                await self._send_crew({"jsonrpc": "2.0", "id": msg.get("id"), "result": {}})
                return
        await self._send_crew(msg)

    async def run(self) -> int:
        await self.start()
        assert self.proc and self.proc.stdout and self._stdout_lines
        crew_waiting_init: set[Any] = set()
        loop = asyncio.get_running_loop()
        crew_q: asyncio.Queue[bytes | None] = asyncio.Queue()

        def _read_crew() -> None:
            try:
                while True:
                    line = sys.stdin.buffer.readline()
                    if not line:
                        loop.call_soon_threadsafe(crew_q.put_nowait, None)
                        return
                    loop.call_soon_threadsafe(crew_q.put_nowait, line)
            except Exception:
                loop.call_soon_threadsafe(crew_q.put_nowait, None)

        import threading

        threading.Thread(target=_read_crew, name="crew-stdin", daemon=True).start()

        stdout = self._stdout_lines
        cursor_task = asyncio.create_task(stdout.readline())
        crew_task = asyncio.create_task(crew_q.get())
        while True:
            done, _ = await asyncio.wait({cursor_task, crew_task}, return_when=asyncio.FIRST_COMPLETED)
            if cursor_task in done:
                try:
                    raw = cursor_task.result()
                except Exception:
                    _log("cursor readline crashed:\n" + traceback.format_exc())
                    cursor_task = asyncio.create_task(stdout.readline())
                    continue
                if not raw:
                    rc = self.proc.returncode if self.proc else None
                    reason = self._fatal or f"cursor ACP stdout closed rc={rc}"
                    _log(f"{reason}; failing open Crew RPCs (was: keep stdin open and hang)")
                    await self._fail_open_crew_rpcs(reason)
                    cursor_task = loop.create_future()
                    continue
                parsed = _parse_line(raw)
                if parsed:
                    try:
                        if parsed.get("method"):
                            await self._handle_cursor_message(parsed)
                        else:
                            await self._handle_cursor_response(parsed, crew_waiting_init)
                    except Exception:
                        _log("cursor-message handler crashed:\n" + traceback.format_exc())
                cursor_task = asyncio.create_task(stdout.readline())
            if crew_task in done:
                raw = crew_task.result()
                if raw is None:
                    _log("crew stdin closed")
                    break
                parsed = _parse_line(raw)
                if parsed:
                    try:
                        if parsed.get("method") == "initialize" and parsed.get("id") is not None:
                            crew_waiting_init.add(parsed.get("id"))
                        await self._handle_crew_request(parsed)
                    except Exception:
                        _log("crew-message handler crashed:\n" + traceback.format_exc())
                        if parsed.get("id") is not None:
                            await self._send_crew(
                                {
                                    "jsonrpc": "2.0",
                                    "id": parsed.get("id"),
                                    "error": {"code": -32603, "message": "cursor-crew-bridge handler error"},
                                }
                            )
                crew_task = asyncio.create_task(crew_q.get())

        if self.proc and self.proc.returncode is None:
            self.proc.terminate()
            try:
                await asyncio.wait_for(self.proc.wait(), timeout=5)
            except asyncio.TimeoutError:
                self.proc.kill()
        return 0


def run_acp(agent: str) -> int:
    try:
        return asyncio.run(AcpBridge(agent).run())
    except FileNotFoundError as exc:
        _log(str(exc))
        sys.stderr.write(str(exc) + "\n")
        return 1
    except KeyboardInterrupt:
        return 130
    except Exception:
        _log("run_acp crashed:\n" + traceback.format_exc())
        return 1
