"""Minimal ACP handshake against the real Cursor Agent via the Crew launcher."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / ".venv" / "Scripts" / "kiro-cli.exe"


def _read(proc: subprocess.Popen, timeout: float) -> dict:
    deadline = time.monotonic() + timeout
    assert proc.stdout
    while time.monotonic() < deadline:
        line = proc.stdout.readline()
        if not line:
            raise RuntimeError("ACP stdout closed")
        line = line.strip()
        if not line:
            continue
        msg = json.loads(line)
        if msg.get("method") == "session/update":
            continue
        if msg.get("method") in {
            "cursor/ask_question",
            "cursor/create_plan",
            "session/request_permission",
        } and msg.get("id") is not None:
            proc.stdin.write(
                json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": {"outcome": {"outcome": "selected", "optionId": "allow-once"}}})
                + "\n"
            )
            proc.stdin.flush()
            continue
        return msg
    raise TimeoutError("no ACP message")


def main() -> int:
    skip = os.environ.get("CURSOR_CREW_SKIP_MCP", "1")
    if "--mcp" in sys.argv:
        skip = "0"
    os.environ["CURSOR_CREW_SKIP_MCP"] = skip
    new_timeout = 180 if skip in {"0", "false", "no", "off"} else 60
    proc = subprocess.Popen(
        [str(LAUNCHER), "acp", "--agent", "kirocrew"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )

    def _err() -> None:
        assert proc.stderr
        for line in proc.stderr:
            sys.stderr.write("stderr: " + line)

    threading.Thread(target=_err, daemon=True).start()
    assert proc.stdin and proc.stdout

    def send(payload: dict) -> None:
        proc.stdin.write(json.dumps(payload) + "\n")
        proc.stdin.flush()

    send(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-08-22",
                "clientInfo": {"name": "kirocrew", "version": "smoke"},
                "clientCapabilities": {"fs": {"readTextFile": False, "writeTextFile": False}, "terminal": False},
            },
        }
    )
    init = _read(proc, 60)
    print("initialize", json.dumps(init.get("result") or init.get("error"), ensure_ascii=True)[:400])
    send(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "session/new",
            "params": {"cwd": str(ROOT), "mcpServers": []},
        }
    )
    created = _read(proc, new_timeout)
    result = created.get("result") or {}
    sid = result.get("sessionId")
    print("session/new", sid, "modes", bool(result.get("modes")), "model", (result.get("models") or {}).get("currentModelId"))
    if not sid:
        print("FAIL", created)
        proc.kill()
        return 1
    send(
        {
            "jsonrpc": "2.0",
            "id": 21,
            "method": "session/set_mode",
            "params": {"sessionId": sid, "modeId": "kirocrew"},
        }
    )
    mode = _read(proc, 15)
    print("set_mode", mode.get("result") if "result" in mode else mode.get("error"))
    send(
        {
            "jsonrpc": "2.0",
            "id": 22,
            "method": "session/set_model",
            "params": {"sessionId": sid, "modelId": "claude-opus-5"},
        }
    )
    model = _read(proc, 15)
    print("set_model", model.get("result") if "result" in model else model.get("error"))
    send(
        {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "session/prompt",
            "params": {
                "sessionId": sid,
                "prompt": [{"type": "text", "text": "Reply with exactly PONG and nothing else."}],
            },
        }
    )
    chunks = []
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        line = proc.stdout.readline()
        if not line:
            break
        msg = json.loads(line)
        if msg.get("id") == 5:
            print("prompt_result", msg.get("result") or msg.get("error"))
            print("text", "".join(chunks)[:200])
            time.sleep(8)
            alive = proc.poll() is None
            print("still_alive_after_handshake", alive, "rc", proc.poll())
            proc.kill()
            ok = "PONG" in "".join(chunks).upper() or bool((msg.get("result") or {}).get("stopReason"))
            return 0 if ok and alive else 1
        if msg.get("method") == "session/update":
            params = msg.get("params") or {}
            update = params.get("update") or params
            if update.get("sessionUpdate") in {"agent_message_chunk", "agent_thought_chunk"}:
                content = update.get("content") or {}
                if isinstance(content, dict) and content.get("text"):
                    chunks.append(content["text"])
        elif msg.get("id") is not None and msg.get("method"):
            proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": {}}) + "\n")
            proc.stdin.flush()
    proc.kill()
    print("TIMEOUT chunks", "".join(chunks)[:200])
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
