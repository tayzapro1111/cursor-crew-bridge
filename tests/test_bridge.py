import json

from cursor_crew_bridge.acp_bridge import (
    MODE_MAP,
    _ask_question_result,
    _ask_question_text,
    _inject_modes,
    _map_permission_result,
    _normalize_update,
    _rewrite_model,
)
from cursor_crew_bridge.agent_mcp import mcp_servers_for_acp
from cursor_crew_bridge.config import (
    KNOWN_GROK_MODELS,
    LITE_MODEL,
    catalog_models,
    is_lite_agent,
    resolve_cursor_model,
    skip_mcp,
)
from cursor_crew_bridge.launcher import dispatch
from cursor_crew_bridge.native_parity import normalize_fs_path
from cursor_crew_bridge.reaper import classify_command


def test_rewrite_model_pins_grok_xhigh() -> None:
    assert _rewrite_model("auto") == "cursor-grok-4.6-xhigh"
    assert _rewrite_model("claude-sonnet-4") == "cursor-grok-4.6-xhigh"
    assert "xhigh" in _rewrite_model("grok-4.6-xhigh")
    assert _rewrite_model("cursor-grok-4.6") in KNOWN_GROK_MODELS
    assert _rewrite_model("cursor-grok-4.6") != "cursor-grok-4.6"


def test_lite_model_is_valid_cursor_id() -> None:
    assert LITE_MODEL in KNOWN_GROK_MODELS
    assert LITE_MODEL != "cursor-grok-4.6"
    assert resolve_cursor_model("cursor-grok-4.6", lite=True) == "cursor-grok-4.6-high-fast"
    assert resolve_cursor_model("cursor-grok-4.6-high-fast", lite=True) == "cursor-grok-4.6-high-fast"


def test_mode_map_covers_crew_agents() -> None:
    assert MODE_MAP["kirocrew"] == "agent"
    assert MODE_MAP["kirocrew-conductor"] == "plan"
    assert MODE_MAP["kirocrew-lite"] == "ask"
    assert MODE_MAP["orchestrator"] == "agent"
    assert MODE_MAP["autopilot"] == "agent"


def test_lite_agent_skips_full_mcp_roster() -> None:
    assert is_lite_agent("kirocrew-lite") is True
    assert is_lite_agent("kirocrew") is False


def test_ask_question_does_not_auto_pick_first() -> None:
    from cursor_crew_bridge.native_parity import (
        ASK_USER_QUESTION_TITLE,
        cursor_ask_crew_messages,
        cursor_ask_crew_payload,
    )

    params = {
        "questions": [
            {
                "id": "q1",
                "prompt": "Which stage?",
                "options": [{"id": "a", "label": "Stage 3"}, {"id": "b", "label": "Stop"}],
            }
        ]
    }
    result = _ask_question_result(params)
    assert result["outcome"]["outcome"] == "skipped"
    assert result["outcome"]["outcome"] != "selected"
    payload = cursor_ask_crew_payload(params)
    assert payload is not None
    assert payload["questions"][0]["question"] == "Which stage?"
    assert payload["questions"][0]["options"][0]["label"] == "Stage 3"
    assert "description" not in payload
    frames = cursor_ask_crew_messages("sid-q", params, call_id="cursor-ask-1")
    assert frames[0]["params"]["update"]["title"] == ASK_USER_QUESTION_TITLE
    assert frames[0]["params"]["update"]["rawInput"]["questions"][0]["question"] == "Which stage?"
    assert frames[1]["params"]["update"]["status"] == "completed"
    text = _ask_question_text(params)
    assert "Which stage?" in text
    assert "Stage 3" in text


def test_inject_modes_lite_pins_high_fast() -> None:
    result = _inject_modes({"sessionId": "s-lite"}, "kirocrew-lite")
    assert result["models"]["currentModelId"] == "cursor-grok-4.6-high-fast"
    assert result["modes"]["currentModeId"] == "kirocrew-lite"


def test_inject_modes_advertises_kirocrew() -> None:
    result = _inject_modes({"sessionId": "s1"}, "kirocrew")
    ids = [m["id"] for m in result["modes"]["availableModes"]]
    assert "kirocrew" in ids
    assert result["models"]["currentModelId"] == "cursor-grok-4.6-xhigh"
    advertised = result["models"]["availableModels"]
    assert all("modelId" in item for item in advertised)
    assert advertised[0]["modelId"] == "cursor-grok-4.6-xhigh"
    alias_ids = {item["modelId"] for item in advertised}
    assert "claude-opus-5" in alias_ids
    assert "auto" in alias_ids
    catalog = {item["model_name"] for item in catalog_models()}
    assert catalog <= alias_ids
    grok = next(item for item in advertised if item["modelId"] == "cursor-grok-4.6-xhigh")
    assert grok["contextWindow"] == 256_000
    assert grok["context_window_tokens"] == 256_000
    fast = next(item for item in advertised if item["modelId"] == "cursor-grok-4.6-high-fast")
    assert fast["contextWindow"] == 256_000
    assert fast["context_window_tokens"] == 256_000


def test_normalize_flat_session_update() -> None:
    msg = {
        "jsonrpc": "2.0",
        "method": "session/update",
        "params": {"sessionId": "s", "sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": "hi"}},
    }
    out = _normalize_update(msg)
    assert out["params"]["update"]["sessionUpdate"] == "agent_message_chunk"
    assert out["params"]["update"]["content"]["text"] == "hi"


def test_normalize_rewrites_cursor_edit_title() -> None:
    path = r"D:\Razrabotka\vpnsite\shutdown-fyi\web\src\styles\global.css"
    msg = {
        "jsonrpc": "2.0",
        "method": "session/update",
        "params": {
            "sessionId": "s",
            "sessionUpdate": "tool_call_update",
            "toolCallId": "call-36",
            "title": f"Edit `{path}`",
        },
    }
    out = _normalize_update(msg)
    update = out["params"]["update"]
    assert out["params"]["sessionId"] == "s"
    assert update["title"] == "Editing global.css"
    assert update["kind"] == "edit"
    assert update["rawInput"]["path"] == normalize_fs_path(path)
    assert update["toolCallId"] == "call-36"


def test_permission_option_mapping() -> None:
    advertised = [{"optionId": "allow-once", "kind": "allow_once"}]
    mapped = _map_permission_result(
        {"outcome": {"outcome": "selected", "optionId": "allow_once"}},
        advertised,
    )
    assert mapped["outcome"]["optionId"] == "allow-once"


def test_permission_auto_allow() -> None:
    from cursor_crew_bridge.acp_bridge import _permission_allow

    result = _permission_allow(
        [{"optionId": "allow-once", "kind": "allow_once"}, {"optionId": "reject-once"}]
    )
    assert result["outcome"]["optionId"] == "allow-once"


def test_session_core_set_mode_model_permission_and_plumbing() -> None:
    """Stage 6: set_mode/set_model honesty, permission card, plumbing updates."""
    import asyncio

    from cursor_crew_bridge.acp_bridge import AcpBridge, DROP_UPDATES

    assert DROP_UPDATES == set()

    bridge = AcpBridge("kirocrew")
    bridge._session_id = "sid-core"
    crew: list[dict] = []
    cursor: list[dict] = []

    async def send_crew(msg: dict) -> None:
        crew.append(msg)

    async def send_cursor(msg: dict, **_kwargs) -> None:
        cursor.append(msg)

    bridge._send_crew = send_crew  # type: ignore[method-assign]
    bridge._send_cursor = send_cursor  # type: ignore[method-assign]

    async def run() -> None:
        bridge._track_forward(20, "session/new")
        await bridge._handle_cursor_response(
            {
                "jsonrpc": "2.0",
                "id": 20,
                "result": {"sessionId": "sid-core"},
            },
            set(),
        )
        await bridge._handle_crew_request(
            {
                "jsonrpc": "2.0",
                "id": 21,
                "method": "session/set_mode",
                "params": {"sessionId": "sid-core", "modeId": "kirocrew"},
            }
        )
        await bridge._handle_crew_request(
            {
                "jsonrpc": "2.0",
                "id": 22,
                "method": "session/set_model",
                "params": {"sessionId": "sid-core", "modelId": "claude-opus-5"},
            }
        )
        await bridge._handle_crew_request(
            {
                "jsonrpc": "2.0",
                "id": 23,
                "method": "session/set_mode",
                "params": {"sessionId": "sid-core", "modeId": "not-a-real-agent"},
            }
        )
        await bridge._handle_cursor_message(
            {
                "jsonrpc": "2.0",
                "id": 30,
                "method": "session/request_permission",
                "params": {
                    "sessionId": "sid-core",
                    "toolCall": {"toolCallId": "t1", "title": "Edit file", "kind": "edit"},
                    "options": [
                        {"optionId": "allow-once", "name": "Allow once"},
                        {"optionId": "reject-once", "name": "Reject"},
                    ],
                },
            }
        )
        await bridge._handle_crew_request(
            {
                "jsonrpc": "2.0",
                "id": 30,
                "result": {"outcome": {"outcome": "selected", "optionId": "allow_once"}},
            }
        )
        await bridge._handle_cursor_message(
            {
                "jsonrpc": "2.0",
                "method": "session/update",
                "params": {
                    "sessionId": "sid-core",
                    "update": {
                        "sessionUpdate": "current_mode_update",
                        "currentModeId": "agent",
                    },
                },
            }
        )
        await bridge._handle_cursor_message(
            {
                "jsonrpc": "2.0",
                "method": "session/update",
                "params": {
                    "sessionId": "sid-core",
                    "update": {
                        "sessionUpdate": "available_commands_update",
                        "availableCommands": [{"name": "compact", "description": "Compact"}],
                    },
                },
            }
        )

    asyncio.run(run())

    new_ack = next(item for item in crew if item.get("id") == 20)
    assert new_ack["result"]["sessionId"] == "sid-core"
    assert new_ack["result"]["models"]["currentModelId"] == "cursor-grok-4.6-xhigh"
    assert new_ack["result"]["modes"]["currentModeId"] == "kirocrew"
    assert not any(item.get("method") == "session/set_mode" for item in cursor)
    assert not any(item.get("method") == "session/set_model" for item in cursor)

    mode_ack = next(item for item in crew if item.get("id") == 21)
    assert mode_ack["result"]["modes"]["currentModeId"] == "kirocrew"
    mode_updates = [
        item
        for item in crew
        if (item.get("params") or {}).get("update", {}).get("sessionUpdate") == "current_mode_update"
    ]
    assert mode_updates
    assert mode_updates[0]["params"]["update"]["currentModeId"] == "kirocrew"

    model_ack = next(item for item in crew if item.get("id") == 22)
    assert model_ack["result"]["models"]["currentModelId"] == "cursor-grok-4.6-xhigh"

    unknown = next(item for item in crew if item.get("id") == 23)
    assert unknown["error"]["code"] == -32602

    perm = next(item for item in crew if item.get("method") == "session/request_permission")
    assert perm["id"] == 30
    assert perm["params"]["options"][0]["kind"] == "allow_once"
    assert perm["params"]["options"][0]["id"] == "allow-once"
    assert perm["params"]["toolCall"]["kind"] == "edit"
    assert perm["params"]["toolCall"]["_meta"]["kiro"]["toolName"] == "fs_write"
    mapped = next(item for item in cursor if item.get("id") == 30 and "result" in item)
    assert mapped["result"]["outcome"]["optionId"] == "allow-once"

    assert any(
        (item.get("params") or {}).get("update", {}).get("currentModeId") == "kirocrew"
        for item in crew
        if (item.get("params") or {}).get("update", {}).get("sessionUpdate") == "current_mode_update"
    )
    commands = next(
        item
        for item in crew
        if (item.get("params") or {}).get("update", {}).get("sessionUpdate")
        == "available_commands_update"
    )
    assert commands["params"]["update"]["availableCommands"][0]["name"] == "compact"


def test_mcp_loader_reads_local_agent(tmp_path, monkeypatch) -> None:
    agents = tmp_path / "agents"
    agents.mkdir()
    (agents / "kirocrew.json").write_text(
        json.dumps(
            {
                "name": "kirocrew",
                "mcpServers": {
                    "demo": {"command": "echo", "args": ["ok"], "env": {"X": "1"}}
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("cursor_crew_bridge.agent_mcp.agents_dir", lambda: agents)
    servers = mcp_servers_for_acp("kirocrew")
    assert servers[0]["name"] == "demo"
    assert servers[0]["command"] == "echo"
    assert servers[0]["env"] == [{"name": "X", "value": "1"}]


def test_dispatch_version_and_whoami(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        "cursor_crew_bridge.launcher.kiro_whoami_json",
        lambda: {"email": "a@b.c", "accountType": "Cursor"},
    )
    monkeypatch.setattr("cursor_crew_bridge.launcher.print_version", lambda: print("kiro-cli 2.15.0-cursor-crew-bridge"))
    assert dispatch(["--version"]) == 0
    assert "kiro-cli" in capsys.readouterr().out
    assert dispatch(["whoami", "--format", "json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["email"] == "a@b.c"
    assert dispatch(["agent", "validate", "--path", "x.json"]) == 0
    assert dispatch(["chat", "--no-interactive"]) == 0
    capsys.readouterr()
    assert dispatch(["chat", "--list-models", "--format", "json", "--no-interactive"]) == 0
    listed = json.loads(capsys.readouterr().out)
    assert listed["models"][0]["model_id"] == listed["models"][0]["model_name"]
    assert listed["models"][0]["model_id"] == "cursor-grok-4.6-xhigh"
    assert listed["models"][0]["context_window_tokens"] == 256_000


def test_skip_mcp_defaults_off(monkeypatch) -> None:
    monkeypatch.delenv("CURSOR_CREW_SKIP_MCP", raising=False)
    assert skip_mcp() is False
    monkeypatch.setenv("CURSOR_CREW_SKIP_MCP", "1")
    assert skip_mcp() is True
    monkeypatch.setenv("CURSOR_CREW_SKIP_MCP", "0")
    assert skip_mcp() is False


def test_reaper_ignores_next_and_cursor_ide() -> None:
    next_cmd = r"node.exe D:\testcscase\frontend\node_modules\next\dist\server\lib\start-server.js"
    assert classify_command("node.exe", next_cmd) == "keep"
    ide = r"C:\Users\admin\AppData\Local\Programs\cursor\Cursor.exe"
    assert classify_command("Cursor.exe", ide) == "keep"


def test_reaper_flags_leaked_cursor_acp() -> None:
    cmd = (
        r'"C:\Program Files\nodejs\node.exe" '
        r"C:\Users\admin\AppData\Roaming\Cursor\User\globalStorage\anysphere.cursor-agent-worker"
        r"\agent-cli\.local\share\cursor-agent\versions\2026.09.02-c22c1a3\index.js "
        r"--auth-token redacted --model cursor-grok-4.6-xhigh --trust acp"
    )
    assert classify_command("node.exe", cmd) == "acp-leak"


def test_env_upsert_enables_mcp(tmp_path) -> None:
    from cursor_crew_bridge.install_env import remove_env_keys, upsert_env_values

    env = tmp_path / ".env"
    upsert_env_values({"KIROCREW_KIRO_BIN": "x", "CURSOR_CREW_SKIP_MCP": "1"}, path=env)
    upsert_env_values({"CURSOR_CREW_SKIP_MCP": "0"}, path=env)
    assert "CURSOR_CREW_SKIP_MCP=0" in env.read_text(encoding="utf-8")
    remove_env_keys({"CURSOR_CREW_SKIP_MCP"}, path=env)
    assert "CURSOR_CREW_SKIP_MCP" not in env.read_text(encoding="utf-8")


def test_prepare_cwd_creates_worker_log(tmp_path, monkeypatch) -> None:
    from cursor_crew_bridge.workspace import _slugs_for, prepare_cwd

    monkeypatch.setattr("cursor_crew_bridge.workspace.Path.home", lambda: tmp_path)
    cwd = tmp_path / "work"
    prepared = prepare_cwd(str(cwd))
    slug = _slugs_for(prepared)[0]
    worker = tmp_path / ".cursor" / "projects" / slug / "worker.log"
    assert worker.is_file()


def test_linebuf_keeps_oversize_line_and_next() -> None:
    import asyncio

    from cursor_crew_bridge.acp_bridge import _LineBuf, _parse_line

    async def _run() -> tuple[bytes, dict | None]:
        reader = asyncio.StreamReader(limit=64)
        payload = b"x" * 200 + b"\n" + b'{"ok": true}\n'
        reader.feed_data(payload)
        reader.feed_eof()
        lines = _LineBuf(reader, chunk=32)
        first = await lines.readline()
        nxt = await lines.readline()
        return first, _parse_line(nxt)

    first, parsed = asyncio.run(_run())
    assert first == b"x" * 200 + b"\n"
    assert parsed == {"ok": True}


def test_crew_outbound_splits_huge_text(monkeypatch) -> None:
    import cursor_crew_bridge.acp_bridge as acp

    monkeypatch.setattr(acp, "CREW_LINE_MAX", 2000)
    monkeypatch.setattr(acp, "CREW_TEXT_CHUNK", 80)
    text = "A" * 3000
    msg = {
        "jsonrpc": "2.0",
        "method": "session/update",
        "params": {
            "sessionId": "s",
            "update": {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": text}},
        },
    }
    frames = acp.crew_outbound_messages(msg)
    assert len(frames) >= 2
    joined = "".join(f["params"]["update"]["content"]["text"] for f in frames)
    assert joined == text


def test_linebuf_two_calls_keep_leftover() -> None:
    import asyncio

    from cursor_crew_bridge.acp_bridge import _LineBuf, _parse_line

    async def _run() -> dict | None:
        reader = asyncio.StreamReader(limit=64)
        reader.feed_data(b"x" * 200 + b"\n" + b'{"ok": true}\n')
        reader.feed_eof()
        buf = _LineBuf(reader, chunk=32)
        await buf.readline()
        return _parse_line(await buf.readline())

    assert asyncio.run(_run()) == {"ok": True}


def test_catalog_window_is_extra_high_256k() -> None:
    rows = catalog_models()
    assert {row["context_window_tokens"] for row in rows} == {256_000}
    ids = {row["model_id"] for row in rows}
    assert "cursor-grok-4.6-xhigh" in ids
    assert "cursor-grok-4.6-high-fast" in ids


def _crew_panel_reading(used: int, window: int) -> dict:
    """Mirror Crew ``chat_handlers._context_reading`` for the dashboard bar."""

    if not window and not used:
        return {}
    pct = round((used / window) * 100, 1) if window else 0.0
    fields: dict = {"context_pct": pct, "context_stale": False}
    if window:
        fields["context_window_tokens"] = int(window)
        if used:
            fields["context_used_tokens"] = int(used)
    if not pct and "context_window_tokens" not in fields:
        return {}
    return fields


def test_usage_update_clamps_one_million_window() -> None:
    from cursor_crew_bridge.acp_bridge import _normalize_update

    msg = {
        "jsonrpc": "2.0",
        "method": "session/update",
        "params": {
            "sessionId": "s",
            "sessionUpdate": "usage_update",
            "used": 180000,
            "size": 1_000_000,
        },
    }
    out = _normalize_update(msg)
    assert out["params"]["update"]["size"] == 256_000
    assert out["params"]["update"]["used"] == 180000
    panel = _crew_panel_reading(180000, out["params"]["update"]["size"])
    assert panel["context_window_tokens"] == 256_000
    assert panel["context_pct"] != 18.0
    assert 70 <= panel["context_pct"] <= 71


def test_usage_update_pins_small_cursor_window_and_clamps_used() -> None:
    from cursor_crew_bridge.acp_bridge import _normalize_update

    msg = {
        "jsonrpc": "2.0",
        "method": "session/update",
        "params": {
            "sessionId": "s",
            "update": {
                "sessionUpdate": "usage_update",
                "used": 400_000,
                "size": 200_000,
            },
        },
    }
    out = _normalize_update(msg)
    assert out["params"]["update"]["size"] == 256_000
    assert out["params"]["update"]["used"] == 256_000


def test_session_new_emits_256k_meter_not_empty() -> None:
    import asyncio

    from cursor_crew_bridge.acp_bridge import AcpBridge

    bridge = AcpBridge("kirocrew")
    crew: list[dict] = []

    async def send_crew(msg: dict) -> None:
        crew.append(msg)

    async def send_cursor(msg: dict, **_kwargs) -> None:
        return None

    bridge._send_crew = send_crew  # type: ignore[method-assign]
    bridge._send_cursor = send_cursor  # type: ignore[method-assign]

    async def run() -> None:
        bridge._track_forward(1, "session/new")
        await bridge._handle_cursor_response(
            {"jsonrpc": "2.0", "id": 1, "result": {"sessionId": "sid-meter"}},
            set(),
        )

    asyncio.run(run())
    usage = [
        item
        for item in crew
        if (item.get("params") or {}).get("update", {}).get("sessionUpdate") == "usage_update"
    ]
    assert usage
    assert usage[0]["params"]["update"]["size"] == 256_000
    assert usage[0]["params"]["update"]["used"] == 0
    panel = _crew_panel_reading(0, 256_000)
    assert panel["context_window_tokens"] == 256_000
    assert panel["context_pct"] == 0.0
    assert "context_used_tokens" not in panel


def test_crew_outbound_keeps_image_payload(monkeypatch) -> None:
    import cursor_crew_bridge.acp_bridge as acp

    monkeypatch.setattr(acp, "CREW_LINE_MAX", 200)
    monkeypatch.setattr(acp, "CREW_TEXT_CHUNK", 40)
    data = "A" * 400
    msg = {
        "jsonrpc": "2.0",
        "method": "session/update",
        "params": {
            "sessionId": "s",
            "update": {
                "sessionUpdate": "agent_message_chunk",
                "content": {"type": "image", "data": data, "mimeType": "image/png"},
            },
        },
    }
    frames = acp.crew_outbound_messages(msg)
    assert len(frames) == 1
    assert frames[0]["params"]["update"]["content"]["data"] == data
    assert frames[0]["params"]["update"]["content"]["type"] == "image"


def test_mcp_http_server_shape() -> None:
    from cursor_crew_bridge.agent_mcp import to_cursor_mcp

    converted = to_cursor_mcp({"url": "https://example.invalid/mcp", "headers": {"A": "1"}}, "remote")
    assert converted is not None
    assert converted["url"].startswith("https://")
    assert converted["type"] == "http"


def test_gateway_windows_patch(tmp_path, monkeypatch) -> None:
    from cursor_crew_bridge import profiles

    monkeypatch.setattr(profiles, "data_home", lambda: tmp_path)
    path = tmp_path / "model_windows.json"
    path.write_text('{"cursor-grok-4.6-xhigh": 1000000, "auto": 1000000}', encoding="utf-8")
    profiles._patch_model_windows(gateway=True)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["cursor-grok-4.6-xhigh"] == 256000
    assert data["auto"] == 256000
    assert data["Grok 4.6 Extra High"] == 256000
    assert data["cursor-grok-4.6-high-fast"] == 256000


def test_gateway_profile_enables_eager_spawn_and_core_stub(tmp_path, monkeypatch) -> None:
    from cursor_crew_bridge import profiles

    monkeypatch.setattr(profiles, "data_home", lambda: tmp_path)
    path = tmp_path / "config.json"
    path.write_text("{}", encoding="utf-8")
    profiles._patch_crew_config(model="cursor-grok-4.6-xhigh", gateway=True)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["session"]["eager_spawn"] is True
    assert "kirocrew-core" in data["mcp_gateway"]["stub_servers"]
    assert data["orchestrator"]["stage_timeout_seconds"] == 3600


def test_gateway_profile_creates_missing_config(tmp_path, monkeypatch) -> None:
    from cursor_crew_bridge import profiles

    monkeypatch.setattr(profiles, "data_home", lambda: tmp_path)
    profiles._patch_crew_config(model="cursor-grok-4.6-xhigh", gateway=True)
    data = json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))
    assert data["agent"]["model"] == "cursor-grok-4.6-xhigh"
    assert data["session"]["eager_spawn"] is True


def test_discover_project_dir_from_nested_file(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("CURSOR_CREW_HOME", raising=False)
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "cursor-crew-bridge"\n',
        encoding="utf-8",
    )
    nested = tmp_path / "src" / "cursor_crew_bridge" / "config.py"
    nested.parent.mkdir(parents=True)
    nested.write_text("#", encoding="utf-8")
    from cursor_crew_bridge.config import discover_project_dir

    assert discover_project_dir(start=nested) == tmp_path


def test_discover_project_dir_env(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("CURSOR_CREW_HOME", str(tmp_path))
    from cursor_crew_bridge.config import discover_project_dir

    assert discover_project_dir() == tmp_path


def test_cli_help_lists_setup(capsys) -> None:
    from cursor_crew_bridge.cli import cmd_help

    assert cmd_help() == 0
    out = capsys.readouterr().out
    assert "doctor" in out
    assert "gateway" in out
    assert "setup" in out


def test_doctor_format_ready() -> None:
    from cursor_crew_bridge.doctor import Check, format_report, required_failed

    checks = [Check(id="python", ok=True, required=True, title="Python", detail="3.12")]
    assert required_failed(checks) == []
    assert "Ready" in format_report(checks)


def test_doctor_format_missing() -> None:
    from cursor_crew_bridge.doctor import Check, format_report, required_failed

    checks = [
        Check(
            id="cursor_login",
            ok=False,
            required=True,
            title="Cursor login",
            detail="none",
            hint="sign in",
        )
    ]
    assert [item.id for item in required_failed(checks)] == ["cursor_login"]
    text = format_report(checks)
    assert "Not ready" in text
    assert "sign in" in text


def test_auth_db_candidates_keep_windows_path() -> None:
    from cursor_crew_bridge.cursor_auth import AUTH_DB, auth_db_candidates

    paths = auth_db_candidates()
    assert AUTH_DB in paths


def test_merge_mcp_prefers_incoming_stub() -> None:
    from cursor_crew_bridge.agent_mcp import merge_mcp_servers

    incoming = [{"name": "kirocrew-core", "command": "stub.exe", "args": ["--id"]}]
    extra = [{"name": "kirocrew-core", "command": "raw.exe"}, {"name": "grafana", "command": "g"}]
    merged = merge_mcp_servers(incoming, extra)
    by_name = {item["name"]: item for item in merged}
    assert by_name["kirocrew-core"]["command"] == "stub.exe"
    assert by_name["grafana"]["command"] == "g"


def test_live_handlers_load_usage_and_stage_steer() -> None:
    """Stage 5: prove 0.3.1 handlers without spawning Cursor or a Crew chat."""
    import asyncio

    from cursor_crew_bridge.acp_bridge import AcpBridge
    from cursor_crew_bridge.config import BRIDGE_VERSION, KIRO_AGENT_NAME, KIRO_AGENT_VERSION

    bridge = AcpBridge("kirocrew")
    crew: list[dict] = []
    cursor: list[dict] = []

    async def send_crew(msg: dict) -> None:
        crew.append(msg)

    async def send_cursor(msg: dict, **_kwargs) -> None:
        cursor.append(msg)

    bridge._send_crew = send_crew  # type: ignore[method-assign]
    bridge._send_cursor = send_cursor  # type: ignore[method-assign]

    async def run() -> None:
        await bridge._handle_crew_request(
            {"jsonrpc": "2.0", "id": 1, "method": "session/load", "params": {"sessionId": "old"}}
        )
        await bridge._handle_crew_request(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "session/prompt",
                "params": {
                    "sessionId": "sid-new",
                    "prompt": [{"type": "text", "text": "Execute Stage 1 of 2 now. ping"}],
                },
            }
        )
        bridge._track_forward(10, "initialize")
        await bridge._handle_cursor_response(
            {"jsonrpc": "2.0", "id": 10, "result": {"protocolVersion": 1}},
            {10},
        )

    asyncio.run(run())

    load = next(item for item in crew if item.get("id") == 1)
    assert load["error"]["code"] == -32001
    assert not any(item.get("method") == "session/load" for item in cursor)

    usage = [
        item
        for item in crew
        if (item.get("params") or {}).get("update", {}).get("sessionUpdate") == "usage_update"
    ]
    assert usage
    assert usage[0]["params"]["sessionId"] == "sid-new"
    assert usage[0]["params"]["update"]["used"] > 0
    assert usage[0]["params"]["update"]["size"] == 256_000
    meta = [item for item in crew if item.get("method") == "_kiro.dev/metadata"]
    assert meta
    assert meta[0]["params"]["contextUsagePercentage"] > 0

    init = next(item for item in crew if item.get("id") == 10)
    assert init["result"]["agentCapabilities"]["loadSession"] is False
    assert init["result"]["agentInfo"]["name"] == KIRO_AGENT_NAME
    assert init["result"]["agentInfo"]["version"] == KIRO_AGENT_VERSION
    assert init["result"]["protocolVersion"] == "2025-08-22"
    assert init["result"]["serverInfo"]["version"] == BRIDGE_VERSION

    forwarded = next(item for item in cursor if item.get("method") == "session/prompt")
    texts = [block.get("text", "") for block in forwarded["params"]["prompt"]]
    blob = "\n".join(texts)
    assert "Cursor ACP delta" in blob
    assert "_capture_stage_result" in blob

def test_help_slash_is_local_not_forwarded() -> None:
    import asyncio

    from cursor_crew_bridge.acp_bridge import AcpBridge

    bridge = AcpBridge("kirocrew")
    crew: list[dict] = []
    cursor: list[dict] = []

    async def send_crew(msg: dict) -> None:
        crew.append(msg)

    async def send_cursor(msg: dict, **_kwargs) -> None:
        cursor.append(msg)

    bridge._send_crew = send_crew  # type: ignore[method-assign]
    bridge._send_cursor = send_cursor  # type: ignore[method-assign]

    async def run() -> None:
        await bridge._handle_crew_request(
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "session/prompt",
                "params": {
                    "sessionId": "sid-help",
                    "prompt": [{"type": "text", "text": "/help"}],
                },
            }
        )
        await bridge._handle_crew_request(
            {
                "jsonrpc": "2.0",
                "id": 5,
                "method": "_kiro.dev/commands/execute",
                "params": {"sessionId": "sid-help", "command": {"command": "tools", "args": {}}},
            }
        )

    asyncio.run(run())

    assert not any(item.get("method") == "session/prompt" for item in cursor)
    ended = next(item for item in crew if item.get("id") == 4)
    assert ended["result"]["stopReason"] == "end_turn"
    chunks = [
        item
        for item in crew
        if (item.get("params") or {}).get("update", {}).get("sessionUpdate") == "agent_message_chunk"
    ]
    blob = "\n".join(
        str((item.get("params") or {}).get("update", {}).get("content", {}).get("text") or "")
        for item in chunks
    )
    assert "/compact" in blob
    ack = next(item for item in crew if item.get("id") == 5)
    assert "fs_read" in str((ack.get("result") or {}).get("message") or "")


def test_compact_emits_completed_rotates_cursor_and_keeps_jsonl(tmp_path, monkeypatch) -> None:
    import asyncio
    import json

    from cursor_crew_bridge.acp_bridge import AcpBridge
    from cursor_crew_bridge.native_parity import COMPACTION_COMPLETED_SUMMARY, COMPACT_SEED_PREFACE

    log = tmp_path / "dashboard_chat-6-test.jsonl"
    rows = [
        {"role": "user", "content": "EARLY bind cursor-crew 1:1"},
        {"role": "assistant", "content": "✅ Stage 1 complete"},
        {"role": "user", "content": "LATE Stage 5: Матрица дыр"},
    ]
    log.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    before = log.read_text(encoding="utf-8")
    monkeypatch.setenv("CURSOR_CREW_SESSION_LOG", str(log))

    bridge = AcpBridge("kirocrew")
    bridge._session_id = "sid-c"
    bridge._cursor_sid = "sid-c"
    crew: list[dict] = []
    cursor: list[dict] = []
    rpc_calls: list[str] = []

    async def send_crew(msg: dict) -> None:
        crew.append(msg)

    async def send_cursor(msg: dict, *, bind: bool = True, **_kwargs) -> None:
        cursor.append(bridge._bind_cursor_session(msg) if bind else msg)

    timeouts: list[tuple[str, float]] = []

    async def cursor_rpc(method: str, params: dict, *, timeout: float = 30) -> dict:
        rpc_calls.append(method)
        timeouts.append((method, timeout))
        if method == "session/new":
            return {"jsonrpc": "2.0", "id": 1, "result": {"sessionId": "cursor-rotated"}}
        assert "EARLY bind cursor-crew 1:1" in params["prompt"][0]["text"]
        assert COMPACT_SEED_PREFACE in params["prompt"][0]["text"]
        assert params["sessionId"] == "cursor-rotated"
        return {"jsonrpc": "2.0", "id": 2, "result": {"stopReason": "end_turn"}}

    bridge._send_crew = send_crew  # type: ignore[method-assign]
    bridge._send_cursor = send_cursor  # type: ignore[method-assign]
    bridge._cursor_rpc = cursor_rpc  # type: ignore[method-assign]

    async def run() -> None:
        await bridge._handle_crew_request(
            {
                "jsonrpc": "2.0",
                "id": 7,
                "method": "session/prompt",
                "params": {
                    "sessionId": "sid-c",
                    "prompt": [
                        {
                            "type": "text",
                            "text": "/compact Preserve this session context in the summary:\nhold",
                        }
                    ],
                },
            }
        )
        await bridge._handle_crew_request(
            {
                "jsonrpc": "2.0",
                "id": 8,
                "method": "_kiro.dev/compaction/status",
                "params": {"sessionId": "sid-c"},
            }
        )
        await bridge._handle_crew_request(
            {
                "jsonrpc": "2.0",
                "id": 9,
                "method": "_kiro.dev/commands/execute",
                "params": {"sessionId": "sid-c", "command": {"command": "compact", "args": {}}},
            }
        )
        await bridge._handle_crew_request(
            {
                "jsonrpc": "2.0",
                "id": 10,
                "method": "session/prompt",
                "params": {
                    "sessionId": "sid-c",
                    "prompt": [{"type": "text", "text": "continue after compact"}],
                },
            }
        )

    asyncio.run(run())

    assert rpc_calls == ["session/new", "session/prompt"]
    assert timeouts[0] == ("session/new", 180.0)
    assert timeouts[1] == ("session/prompt", 90)
    cancel = next(item for item in cursor if item.get("method") == "session/cancel")
    assert cancel["params"]["sessionId"] == "sid-c"
    assert bridge._session_id == "sid-c"
    assert bridge._cursor_sid == "cursor-rotated"
    assert log.read_text(encoding="utf-8") == before
    notes = [item for item in crew if item.get("method") == "_kiro.dev/compaction/status"]
    assert len(notes) == 1
    assert notes[0]["params"]["status"]["type"] == "completed"
    assert notes[0]["params"]["summary"] == COMPACTION_COMPLETED_SUMMARY
    assert notes[0]["params"]["sessionId"] == "sid-c"
    ended = next(item for item in crew if item.get("id") == 7)
    assert ended["result"]["stopReason"] == "end_turn"
    poll = next(item for item in crew if item.get("id") == 8)
    assert poll["result"]["status"] == "idle"
    assert poll["result"]["supported"] is True
    execute_ack = next(item for item in crew if item.get("id") == 9)
    assert execute_ack["result"] == {}
    usage = [
        item
        for item in crew
        if (item.get("params") or {}).get("update", {}).get("sessionUpdate") == "usage_update"
    ]
    assert usage
    assert usage[-1]["params"]["sessionId"] == "sid-c"
    assert usage[-1]["params"]["update"]["used"] < 95_000
    assert usage[-1]["params"]["update"]["size"] == 256_000
    forwarded = next(item for item in cursor if item.get("method") == "session/prompt" and item.get("id") == 10)
    assert forwarded["params"]["sessionId"] == "cursor-rotated"


def test_late_compact_session_new_is_not_forwarded_to_crew() -> None:
    import asyncio

    from cursor_crew_bridge.acp_bridge import AcpBridge

    bridge = AcpBridge("kirocrew")
    bridge._session_id = "sid-c"
    crew: list[dict] = []

    async def send_crew(msg: dict) -> None:
        crew.append(msg)

    bridge._send_crew = send_crew  # type: ignore[method-assign]

    asyncio.run(
        bridge._handle_cursor_response(
            {"jsonrpc": "2.0", "id": 99, "result": {"sessionId": "cursor-late"}},
            set(),
        )
    )
    assert crew == []
    assert bridge._cursor_sid == "cursor-late"
    assert bridge._session_id == "sid-c"


def test_compact_adopts_late_session_new_after_timeout(monkeypatch) -> None:
    import asyncio

    from cursor_crew_bridge import acp_bridge as mod
    from cursor_crew_bridge.acp_bridge import AcpBridge
    from cursor_crew_bridge.native_parity import COMPACTION_COMPLETED_SUMMARY

    monkeypatch.setattr(mod, "COMPACT_SESSION_NEW_GRACE_S", 0.05)
    bridge = AcpBridge("kirocrew")
    bridge._session_id = "sid-c"
    bridge._cursor_sid = "sid-c"
    crew: list[dict] = []

    async def send_crew(msg: dict) -> None:
        crew.append(msg)

    async def send_cursor(_msg: dict, **_kwargs) -> None:
        return None

    async def cursor_rpc(method: str, params: dict, *, timeout: float = 30) -> dict:
        if method == "session/new":
            assert timeout == 180.0

            async def adopt() -> None:
                await asyncio.sleep(0.01)
                bridge._cursor_sid = "cursor-late"

            asyncio.create_task(adopt())
            raise TimeoutError
        assert params["sessionId"] == "cursor-late"
        return {"jsonrpc": "2.0", "id": 2, "result": {"stopReason": "end_turn"}}

    bridge._send_crew = send_crew  # type: ignore[method-assign]
    bridge._send_cursor = send_cursor  # type: ignore[method-assign]
    bridge._cursor_rpc = cursor_rpc  # type: ignore[method-assign]

    asyncio.run(
        bridge._handle_crew_request(
            {
                "jsonrpc": "2.0",
                "id": 7,
                "method": "session/prompt",
                "params": {
                    "sessionId": "sid-c",
                    "prompt": [{"type": "text", "text": "/compact"}],
                },
            }
        )
    )
    notes = [item for item in crew if item.get("method") == "_kiro.dev/compaction/status"]
    assert len(notes) == 1
    assert notes[0]["params"]["status"]["type"] == "completed"
    assert notes[0]["params"]["summary"] == COMPACTION_COMPLETED_SUMMARY
    assert bridge._cursor_sid == "cursor-late"
    assert bridge._session_id == "sid-c"


def test_compact_falls_back_to_failed_when_rotate_unavailable() -> None:
    import asyncio

    from cursor_crew_bridge.acp_bridge import AcpBridge
    from cursor_crew_bridge.native_parity import COMPACTION_FAILED_SUMMARY

    bridge = AcpBridge("kirocrew")
    crew: list[dict] = []
    cursor: list[dict] = []

    async def send_crew(msg: dict) -> None:
        crew.append(msg)

    async def send_cursor(msg: dict, **_kwargs) -> None:
        cursor.append(msg)

    bridge._send_crew = send_crew  # type: ignore[method-assign]
    bridge._send_cursor = send_cursor  # type: ignore[method-assign]

    async def run() -> None:
        await bridge._handle_crew_request(
            {
                "jsonrpc": "2.0",
                "id": 7,
                "method": "session/prompt",
                "params": {
                    "sessionId": "sid-c",
                    "prompt": [{"type": "text", "text": "/compact"}],
                },
            }
        )

    asyncio.run(run())

    failed = [item for item in crew if item.get("method") == "_kiro.dev/compaction/status"]
    assert len(failed) == 1
    assert failed[0]["params"]["status"]["type"] == "failed"
    assert failed[0]["params"]["status"]["error"] == COMPACTION_FAILED_SUMMARY
    ended = next(item for item in crew if item.get("id") == 7)
    assert ended["result"]["stopReason"] == "end_turn"
    failed_at = next(
        i
        for i, item in enumerate(crew)
        if item.get("method") == "_kiro.dev/compaction/status"
        and (item.get("params") or {}).get("status", {}).get("type") == "failed"
    )
    chunk_at = next(
        i
        for i, item in enumerate(crew)
        if (item.get("params") or {}).get("update", {}).get("sessionUpdate") == "agent_message_chunk"
        and "Compact failed" in str((item.get("params") or {}).get("update", {}).get("content", {}))
    )
    ended_at = next(i for i, item in enumerate(crew) if item.get("id") == 7)
    assert failed_at < chunk_at < ended_at


def test_compact_survives_slow_seed_after_rotate() -> None:
    import asyncio

    from cursor_crew_bridge.acp_bridge import AcpBridge
    from cursor_crew_bridge.native_parity import COMPACTION_COMPLETED_SUMMARY

    bridge = AcpBridge("kirocrew")
    bridge._session_id = "sid-c"
    bridge._cursor_sid = "sid-c"
    crew: list[dict] = []

    async def send_crew(msg: dict) -> None:
        crew.append(msg)

    async def send_cursor(_msg: dict, **_kwargs) -> None:
        return None

    async def cursor_rpc(method: str, params: dict, *, timeout: float = 30) -> dict:
        if method == "session/new":
            return {"jsonrpc": "2.0", "id": 1, "result": {"sessionId": "cursor-rotated"}}
        raise TimeoutError("seed prompt still thinking")

    bridge._send_crew = send_crew  # type: ignore[method-assign]
    bridge._send_cursor = send_cursor  # type: ignore[method-assign]
    bridge._cursor_rpc = cursor_rpc  # type: ignore[method-assign]

    asyncio.run(
        bridge._handle_crew_request(
            {
                "jsonrpc": "2.0",
                "id": 7,
                "method": "session/prompt",
                "params": {
                    "sessionId": "sid-c",
                    "prompt": [{"type": "text", "text": "/compact"}],
                },
            }
        )
    )

    notes = [item for item in crew if item.get("method") == "_kiro.dev/compaction/status"]
    assert len(notes) == 1
    assert notes[0]["params"]["status"]["type"] == "completed"
    assert notes[0]["params"]["summary"] == COMPACTION_COMPLETED_SUMMARY
    assert bridge._cursor_sid == "cursor-rotated"
    assert bridge._session_id == "sid-c"


def test_crew_rpc_awaits_cursor_only_for_compact() -> None:
    from cursor_crew_bridge.acp_bridge import _crew_rpc_awaits_cursor

    compact = {
        "jsonrpc": "2.0",
        "id": 7,
        "method": "session/prompt",
        "params": {"sessionId": "sid-c", "prompt": [{"type": "text", "text": "/compact"}]},
    }
    other = {
        "jsonrpc": "2.0",
        "id": 8,
        "method": "session/prompt",
        "params": {"sessionId": "sid-c", "prompt": [{"type": "text", "text": "hello"}]},
    }
    assert _crew_rpc_awaits_cursor(compact) is True
    assert _crew_rpc_awaits_cursor(other) is False
    assert _crew_rpc_awaits_cursor({"method": "session/new"}) is False


def test_compact_dispatch_keeps_cursor_pump_live() -> None:
    import asyncio

    from cursor_crew_bridge.acp_bridge import AcpBridge
    from cursor_crew_bridge.native_parity import COMPACTION_COMPLETED_SUMMARY

    bridge = AcpBridge("kirocrew")
    bridge._session_id = "sid-c"
    bridge._cursor_sid = "sid-c"
    bridge.proc = type("Proc", (), {"stdin": object()})()
    crew: list[dict] = []
    cursor: list[dict] = []

    async def send_crew(msg: dict) -> None:
        crew.append(msg)

    async def send_cursor(msg: dict, **_kwargs) -> None:
        cursor.append(msg)

    bridge._send_crew = send_crew  # type: ignore[method-assign]
    bridge._send_cursor = send_cursor  # type: ignore[method-assign]

    compact = {
        "jsonrpc": "2.0",
        "id": 7,
        "method": "session/prompt",
        "params": {
            "sessionId": "sid-c",
            "prompt": [{"type": "text", "text": "/compact"}],
        },
    }

    async def run() -> None:
        await bridge._dispatch_crew_line(compact, set())
        new_msg = None
        for _ in range(200):
            new_msg = next((item for item in cursor if item.get("method") == "session/new"), None)
            if new_msg:
                break
            await asyncio.sleep(0)
        assert new_msg is not None
        await bridge._handle_cursor_response(
            {"jsonrpc": "2.0", "id": new_msg["id"], "result": {"sessionId": "cursor-rotated"}},
            set(),
        )
        seed = None
        for _ in range(200):
            seed = next((item for item in cursor if item.get("method") == "session/prompt"), None)
            if seed:
                break
            await asyncio.sleep(0)
        assert seed is not None
        await bridge._handle_cursor_message(
            {
                "jsonrpc": "2.0",
                "id": 51,
                "method": "session/request_permission",
                "params": {
                    "sessionId": "cursor-rotated",
                    "options": [{"optionId": "allow-once", "name": "Allow once"}],
                },
            }
        )
        await bridge._handle_cursor_response(
            {"jsonrpc": "2.0", "id": seed["id"], "result": {"stopReason": "end_turn"}},
            set(),
        )
        for _ in range(200):
            if any(
                item.get("method") == "_kiro.dev/compaction/status"
                and (item.get("params") or {}).get("status", {}).get("type") == "completed"
                for item in crew
            ):
                break
            await asyncio.sleep(0)

    asyncio.run(run())

    notes = [item for item in crew if item.get("method") == "_kiro.dev/compaction/status"]
    assert notes and notes[0]["params"]["status"]["type"] == "completed"
    assert notes[0]["params"]["summary"] == COMPACTION_COMPLETED_SUMMARY
    assert bridge._cursor_sid == "cursor-rotated"
    ended = next(item for item in crew if item.get("id") == 7)
    assert ended["result"]["stopReason"] == "end_turn"
    ended_at = next(i for i, item in enumerate(crew) if item.get("id") == 7)
    chunk_at = next(
        i
        for i, item in enumerate(crew)
        if (item.get("params") or {}).get("update", {}).get("sessionUpdate") == "agent_message_chunk"
        and "Compacted in place" in str((item.get("params") or {}).get("update", {}).get("content", {}))
    )
    status_at = next(
        i
        for i, item in enumerate(crew)
        if item.get("method") == "_kiro.dev/compaction/status"
        and (item.get("params") or {}).get("status", {}).get("type") == "completed"
    )
    assert status_at < chunk_at < ended_at
    assert not any(item.get("method") == "session/request_permission" for item in crew)
    allowed = [item for item in cursor if item.get("id") == 51 and "result" in item]
    assert allowed and allowed[0]["result"]["outcome"]["outcome"] == "selected"


def test_compact_status_then_chunk_then_end_turn() -> None:
    import asyncio

    from cursor_crew_bridge.acp_bridge import AcpBridge

    bridge = AcpBridge("kirocrew")
    bridge._session_id = "sid-c"
    bridge._cursor_sid = "sid-c"
    crew: list[dict] = []

    async def send_crew(msg: dict) -> None:
        crew.append(msg)

    async def cursor_rpc(method: str, params: dict, *, timeout: float = 30) -> dict:
        if method == "session/new":
            return {"jsonrpc": "2.0", "id": 1, "result": {"sessionId": "cursor-rotated"}}
        return {"jsonrpc": "2.0", "id": 2, "result": {"stopReason": "end_turn"}}

    async def send_cursor(msg: dict, **_kwargs) -> None:
        return

    bridge._send_crew = send_crew  # type: ignore[method-assign]
    bridge._send_cursor = send_cursor  # type: ignore[method-assign]
    bridge._cursor_rpc = cursor_rpc  # type: ignore[method-assign]

    asyncio.run(
        bridge._handle_crew_request(
            {
                "jsonrpc": "2.0",
                "id": 7,
                "method": "session/prompt",
                "params": {
                    "sessionId": "sid-c",
                    "prompt": [{"type": "text", "text": "/compact"}],
                },
            }
        )
    )
    ended_at = next(i for i, item in enumerate(crew) if item.get("id") == 7)
    chunk_at = next(
        i
        for i, item in enumerate(crew)
        if (item.get("params") or {}).get("update", {}).get("sessionUpdate") == "agent_message_chunk"
        and "Compacted in place" in str((item.get("params") or {}).get("update", {}).get("content", {}))
    )
    status_at = next(
        i
        for i, item in enumerate(crew)
        if item.get("method") == "_kiro.dev/compaction/status"
        and (item.get("params") or {}).get("status", {}).get("type") == "completed"
    )
    assert status_at < chunk_at < ended_at
    assert crew[ended_at]["result"]["stopReason"] == "end_turn"


def test_compact_rotate_drops_session_updates() -> None:
    import asyncio

    from cursor_crew_bridge.acp_bridge import AcpBridge

    bridge = AcpBridge("kirocrew")
    bridge._compact_rotate = True
    crew: list[dict] = []
    cursor: list[dict] = []

    async def send_crew(msg: dict) -> None:
        crew.append(msg)

    async def send_cursor(msg: dict, **_kwargs) -> None:
        cursor.append(msg)

    bridge._send_crew = send_crew  # type: ignore[method-assign]
    bridge._send_cursor = send_cursor  # type: ignore[method-assign]

    asyncio.run(
        bridge._handle_cursor_message(
            {
                "jsonrpc": "2.0",
                "method": "session/update",
                "params": {
                    "sessionId": "sid-new",
                    "update": {"sessionUpdate": "available_commands_update", "availableCommands": []},
                },
            }
        )
    )
    asyncio.run(
        bridge._handle_cursor_message(
            {
                "jsonrpc": "2.0",
                "method": "session/update",
                "params": {
                    "sessionId": "sid-new",
                    "update": {
                        "sessionUpdate": "agent_message_chunk",
                        "content": {"type": "text", "text": "seed leak"},
                    },
                },
            }
        )
    )
    assert crew == []
    assert cursor == []


def test_compact_ignores_crew_session_cancel() -> None:
    import asyncio

    from cursor_crew_bridge.acp_bridge import AcpBridge

    bridge = AcpBridge("kirocrew")
    bridge._compacting = True
    bridge._session_id = "sid-c"
    bridge._cursor_sid = "cursor-rotated"
    cursor: list[dict] = []

    async def send_cursor(msg: dict, **_kwargs) -> None:
        cursor.append(msg)

    bridge._send_cursor = send_cursor  # type: ignore[method-assign]

    asyncio.run(
        bridge._handle_crew_request(
            {
                "jsonrpc": "2.0",
                "method": "session/cancel",
                "params": {"sessionId": "sid-c"},
            }
        )
    )
    assert cursor == []
    assert bridge._turn_cancelled is False


def test_compact_rotate_auto_allows_permissions() -> None:
    import asyncio

    from cursor_crew_bridge.acp_bridge import AcpBridge

    bridge = AcpBridge("kirocrew")
    bridge._compact_rotate = True
    crew: list[dict] = []
    cursor: list[dict] = []

    async def send_crew(msg: dict) -> None:
        crew.append(msg)

    async def send_cursor(msg: dict, **_kwargs) -> None:
        cursor.append(msg)

    bridge._send_crew = send_crew  # type: ignore[method-assign]
    bridge._send_cursor = send_cursor  # type: ignore[method-assign]

    asyncio.run(
        bridge._handle_cursor_message(
            {
                "jsonrpc": "2.0",
                "id": 51,
                "method": "session/request_permission",
                "params": {
                    "sessionId": "sid-c",
                    "options": [{"optionId": "allow-once", "name": "Allow once"}],
                },
            }
        )
    )
    assert crew == []
    assert cursor[0]["result"]["outcome"]["optionId"] == "allow-once"


def test_retired_cursor_session_frames_are_dropped() -> None:
    import asyncio

    from cursor_crew_bridge.acp_bridge import AcpBridge

    bridge = AcpBridge("kirocrew")
    bridge._session_id = "sid-c"
    bridge._cursor_sid = "cursor-rotated"
    bridge._retired_cursor_sids.add("sid-c")
    crew: list[dict] = []
    cursor: list[dict] = []

    async def send_crew(msg: dict) -> None:
        crew.append(msg)

    async def send_cursor(msg: dict, **_kwargs) -> None:
        cursor.append(msg)

    bridge._send_crew = send_crew  # type: ignore[method-assign]
    bridge._send_cursor = send_cursor  # type: ignore[method-assign]

    asyncio.run(
        bridge._handle_cursor_message(
            {
                "jsonrpc": "2.0",
                "method": "session/update",
                "params": {
                    "sessionId": "sid-c",
                    "update": {
                        "sessionUpdate": "agent_message_chunk",
                        "content": {"type": "text", "text": "cancelled leftover"},
                    },
                },
            }
        )
    )
    assert crew == []
    assert cursor == []


def test_first_prompt_after_session_new_replaces_80k_tail(tmp_path, monkeypatch) -> None:
    import asyncio
    import json

    from cursor_crew_bridge.acp_bridge import AcpBridge
    from cursor_crew_bridge.native_parity import (
        CREW_REPLAY_CLOSE,
        CREW_REPLAY_OPEN,
        REPLAY_THREAD_PREFACE,
    )

    log = tmp_path / "dashboard_chat-replay.jsonl"
    log.write_text(
        json.dumps({"role": "user", "content": "EARLY_GOAL bind cursor-crew 1:1"}) + "\n"
        + json.dumps({"role": "tool", "content": "🔧 Read foo.py\n" + ("RAW_TOOL " * 300)}) + "\n"
        + json.dumps({"role": "thought", "content": "HIDDEN_THOUGHT"}) + "\n"
        + json.dumps({"role": "assistant", "content": "✅ Stage 1 complete"}) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("CURSOR_CREW_SESSION_LOG", str(log))

    tail = "Assistant: Stage 5: Матрица дыр\n" + ("t" * 2000)
    first = (
        CREW_REPLAY_OPEN
        + "\n"
        + tail
        + "\n"
        + CREW_REPLAY_CLOSE
        + "\nCURRENT USER REQUEST -- continue\n"
    )
    second = "follow-up without history block"

    bridge = AcpBridge("kirocrew")
    cursor: list[dict] = []

    async def send_crew(msg: dict) -> None:
        return None

    async def send_cursor(msg: dict, **_kwargs) -> None:
        cursor.append(msg)

    bridge._send_crew = send_crew  # type: ignore[method-assign]
    bridge._send_cursor = send_cursor  # type: ignore[method-assign]

    async def run() -> None:
        await bridge._handle_crew_request(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "session/new",
                "params": {"cwd": str(tmp_path), "mcpServers": []},
            }
        )
        await bridge._handle_crew_request(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "session/prompt",
                "params": {
                    "sessionId": "sid-c",
                    "prompt": [{"type": "text", "text": first}],
                },
            }
        )
        await bridge._handle_crew_request(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "session/prompt",
                "params": {
                    "sessionId": "sid-c",
                    "prompt": [{"type": "text", "text": second}],
                },
            }
        )

    asyncio.run(run())

    prompts = [item for item in cursor if item.get("method") == "session/prompt"]
    assert len(prompts) == 2
    first_texts = [block.get("text", "") for block in prompts[0]["params"]["prompt"]]
    rewritten = "\n".join(first_texts)
    assert CREW_REPLAY_OPEN in rewritten
    assert REPLAY_THREAD_PREFACE in rewritten
    assert "EARLY_GOAL bind cursor-crew 1:1" in rewritten
    assert "Read foo.py" in rewritten
    assert "RAW_TOOL" not in rewritten
    assert "HIDDEN_THOUGHT" not in rewritten
    assert "Матрица дыр" not in rewritten
    assert "CURRENT USER REQUEST -- continue" in rewritten
    follow_texts = [block.get("text", "") for block in prompts[1]["params"]["prompt"]]
    assert second in "\n".join(follow_texts)
    assert not any(CREW_REPLAY_OPEN in text for text in follow_texts)
    assert not bridge._awaiting_replay


def test_cancel_notification_keeps_session_and_maps_todos() -> None:
    import asyncio

    from cursor_crew_bridge.acp_bridge import AcpBridge

    bridge = AcpBridge("kirocrew")
    bridge._session_id = "sid-live"
    bridge._prompt_req_id = 44
    crew: list[dict] = []
    cursor: list[dict] = []

    async def send_crew(msg: dict) -> None:
        crew.append(msg)

    async def send_cursor(msg: dict, **_kwargs) -> None:
        cursor.append(msg)

    bridge._send_crew = send_crew  # type: ignore[method-assign]
    bridge._send_cursor = send_cursor  # type: ignore[method-assign]

    async def run() -> None:
        await bridge._handle_cursor_message(
            {
                "jsonrpc": "2.0",
                "id": 90,
                "method": "cursor/update_todos",
                "params": {
                    "sessionId": "sid-live",
                    "todos": [{"id": "1", "content": "Ship", "status": "completed"}],
                },
            }
        )
        await bridge._handle_crew_request(
            {"jsonrpc": "2.0", "method": "session/cancel", "params": {"sessionId": "sid-live"}}
        )
        await bridge._handle_cursor_message(
            {
                "jsonrpc": "2.0",
                "method": "session/update",
                "params": {
                    "sessionId": "sid-live",
                    "update": {
                        "sessionUpdate": "agent_message_chunk",
                        "content": {"type": "text", "text": "should drop"},
                    },
                },
            }
        )
        watch = bridge._cancel_watch
        bridge._clear_cancel_watch()
        if watch is not None:
            try:
                await watch
            except asyncio.CancelledError:
                pass

    asyncio.run(run())
    cancel = next(item for item in cursor if item.get("method") == "session/cancel")
    assert "id" not in cancel
    assert bridge._session_id == "sid-live"
    assert bridge._turn_cancelled is True
    todos = [
        item
        for item in crew
        if (item.get("params") or {}).get("update", {}).get("_meta", {}).get("kiro", {}).get("toolName")
        == "todo_list"
    ]
    assert todos
    assert not any("should drop" in str(item) for item in crew)
    ack = next(item for item in cursor if item.get("id") == 90)
    assert ack["result"]["outcome"]["outcome"] == "accepted"


def test_cursor_extras_ask_task_image_and_plan_wont() -> None:
    import asyncio

    from cursor_crew_bridge.acp_bridge import AcpBridge
    from cursor_crew_bridge.native_parity import ASK_USER_QUESTION_TITLE, CREATE_PLAN_MAPPING

    assert CREATE_PLAN_MAPPING == "wont"

    bridge = AcpBridge("kirocrew")
    bridge._session_id = "sid-x"
    crew: list[dict] = []
    cursor: list[dict] = []

    async def send_crew(msg: dict) -> None:
        crew.append(msg)

    async def send_cursor(msg: dict, **_kwargs) -> None:
        cursor.append(msg)

    bridge._send_crew = send_crew  # type: ignore[method-assign]
    bridge._send_cursor = send_cursor  # type: ignore[method-assign]

    async def run() -> None:
        await bridge._handle_cursor_message(
            {
                "jsonrpc": "2.0",
                "id": 101,
                "method": "cursor/ask_question",
                "params": {
                    "sessionId": "sid-x",
                    "questions": [
                        {
                            "prompt": "Ship now?",
                            "header": "Go",
                            "options": [
                                {"id": "yes", "label": "Yes"},
                                {"id": "no", "label": "No"},
                            ],
                        }
                    ],
                },
            }
        )
        await bridge._handle_cursor_message(
            {
                "jsonrpc": "2.0",
                "id": 102,
                "method": "cursor/create_plan",
                "params": {"sessionId": "sid-x", "plan": "do everything"},
            }
        )
        await bridge._handle_cursor_message(
            {
                "jsonrpc": "2.0",
                "id": 103,
                "method": "cursor/task",
                "params": {"sessionId": "sid-x", "text": "Working on listeners"},
            }
        )
        await bridge._handle_cursor_message(
            {
                "jsonrpc": "2.0",
                "id": 104,
                "method": "cursor/generate_image",
                "params": {
                    "sessionId": "sid-x",
                    "image": {"type": "image", "data": "iVBORw0KGgo", "mimeType": "image/png"},
                },
            }
        )
        await bridge._handle_cursor_message(
            {
                "jsonrpc": "2.0",
                "id": 105,
                "method": "cursor/generate_image",
                "params": {"sessionId": "sid-x", "url": "https://example.invalid/shot.png"},
            }
        )

    asyncio.run(run())

    ask_ack = next(item for item in cursor if item.get("id") == 101)
    assert ask_ack["result"]["outcome"]["outcome"] == "skipped"
    cards = [
        item
        for item in crew
        if (item.get("params") or {}).get("update", {}).get("title") == ASK_USER_QUESTION_TITLE
    ]
    assert cards
    raw = cards[0]["params"]["update"]["rawInput"]
    assert raw["questions"][0]["question"] == "Ship now?"
    assert raw["questions"][0]["options"][0]["label"] == "Yes"
    assert not any(
        "Ship now?" in str((item.get("params") or {}).get("update", {}).get("content", {}))
        for item in crew
        if (item.get("params") or {}).get("update", {}).get("sessionUpdate")
        == "agent_message_chunk"
    )

    plan_ack = next(item for item in cursor if item.get("id") == 102)
    assert plan_ack["result"]["outcome"]["outcome"] == "accepted"
    assert not any("do everything" in str(item) for item in crew)

    thoughts = [
        item
        for item in crew
        if (item.get("params") or {}).get("update", {}).get("sessionUpdate")
        == "agent_thought_chunk"
    ]
    assert thoughts
    assert "Working on listeners" in thoughts[0]["params"]["update"]["content"]["text"]

    images = [
        item
        for item in crew
        if (item.get("params") or {}).get("update", {}).get("content", {}).get("type") == "image"
    ]
    assert images
    assert images[0]["params"]["update"]["content"]["data"] == "iVBORw0KGgo"

    refs = [
        item
        for item in crew
        if "[generated image]"
        in str((item.get("params") or {}).get("update", {}).get("content", {}))
    ]
    assert refs
    assert "https://example.invalid/shot.png" in refs[0]["params"]["update"]["content"]["text"]


def test_permission_options_fill_name_and_label() -> None:
    from cursor_crew_bridge.acp_bridge import _rewrite_permission_options

    rewritten = _rewrite_permission_options(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "session/request_permission",
            "params": {
                "sessionId": "sid-p",
                "options": [
                    {"optionId": "allow-once", "label": "Allow once"},
                    {"optionId": "reject-once", "name": "Reject"},
                ],
            },
        }
    )
    allow, reject = rewritten["params"]["options"]
    assert allow["kind"] == "allow_once"
    assert allow["id"] == "allow-once"
    assert allow["optionId"] == "allow-once"
    assert allow["name"] == "Allow once"
    assert allow["label"] == "Allow once"
    assert reject["kind"] == "reject_once"
    assert reject["name"] == "Reject"
    assert reject["label"] == "Reject"


def test_session_new_mcp_incoming_stub_wins(monkeypatch) -> None:
    import asyncio

    from cursor_crew_bridge.acp_bridge import AcpBridge

    monkeypatch.setattr("cursor_crew_bridge.acp_bridge.skip_mcp", lambda: False)
    monkeypatch.setattr(
        "cursor_crew_bridge.agent_mcp.mcp_servers_for_acp",
        lambda agent: [
            {"name": "kirocrew-core", "command": "raw.exe", "args": [], "env": []},
            {"name": "grafana", "command": "g", "args": [], "env": []},
        ],
    )
    monkeypatch.setattr("cursor_crew_bridge.agent_mcp.overlay_mcp_servers", lambda agent: [])
    monkeypatch.setattr("cursor_crew_bridge.acp_bridge.prepare_cwd", lambda cwd: cwd or ".")

    full = AcpBridge("kirocrew")
    lite = AcpBridge("kirocrew-lite")
    skipped = AcpBridge("kirocrew")
    cursor: list[dict] = []

    async def send_cursor(msg: dict, **_kwargs) -> None:
        cursor.append(msg)

    async def send_crew(_msg: dict) -> None:
        return None

    for bridge in (full, lite, skipped):
        bridge._send_cursor = send_cursor  # type: ignore[method-assign]
        bridge._send_crew = send_crew  # type: ignore[method-assign]

    incoming = [{"name": "kirocrew-core", "command": "stub.exe", "args": ["--id"]}]

    async def run() -> None:
        await full._handle_crew_request(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "session/new",
                "params": {"cwd": ".", "mcpServers": incoming},
            }
        )
        await lite._handle_crew_request(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "session/new",
                "params": {"cwd": ".", "mcpServers": incoming},
            }
        )
        monkeypatch.setattr("cursor_crew_bridge.acp_bridge.skip_mcp", lambda: True)
        await skipped._handle_crew_request(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "session/new",
                "params": {"cwd": ".", "mcpServers": incoming},
            }
        )

    asyncio.run(run())
    new_full = next(item for item in cursor if item.get("id") == 1)
    by_name = {item["name"]: item for item in new_full["params"]["mcpServers"]}
    assert by_name["kirocrew-core"]["command"] == "stub.exe"
    assert by_name["grafana"]["command"] == "g"
    new_lite = next(item for item in cursor if item.get("id") == 2)
    assert new_lite["params"]["mcpServers"] == []
    new_skip = next(item for item in cursor if item.get("id") == 3)
    assert new_skip["params"]["mcpServers"] == []


def test_session_load_forwards_when_cursor_advertises_it() -> None:
    import asyncio

    from cursor_crew_bridge.acp_bridge import AcpBridge

    bridge = AcpBridge("kirocrew")
    bridge._cursor_load_session = True
    crew: list[dict] = []
    cursor: list[dict] = []

    async def send_crew(msg: dict) -> None:
        crew.append(msg)

    async def send_cursor(msg: dict, **_kwargs) -> None:
        cursor.append(msg)

    bridge._send_crew = send_crew  # type: ignore[method-assign]
    bridge._send_cursor = send_cursor  # type: ignore[method-assign]

    async def run() -> None:
        await bridge._handle_crew_request(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "session/load",
                "params": {"sessionId": "sid-live", "cwd": ".", "mcpServers": []},
            }
        )
        bridge._track_forward(10, "initialize")
        await bridge._handle_cursor_response(
            {
                "jsonrpc": "2.0",
                "id": 10,
                "result": {
                    "protocolVersion": 1,
                    "agentCapabilities": {
                        "loadSession": True,
                        "promptCapabilities": {"image": True, "audio": False},
                    },
                },
            },
            {10},
        )

    asyncio.run(run())
    load = next(item for item in cursor if item.get("method") == "session/load")
    assert load["params"]["sessionId"] == "sid-live"
    assert "mcpServers" in load["params"]
    assert not any(item.get("id") == 1 and "error" in item for item in crew)
    init = next(item for item in crew if item.get("id") == 10)
    assert init["result"]["agentCapabilities"]["loadSession"] is True
    assert init["result"]["agentCapabilities"]["promptCapabilities"]["image"] is True


def test_resolved_mcp_overlay_wins_over_agent_spec(tmp_path, monkeypatch) -> None:
    from cursor_crew_bridge.agent_mcp import resolved_mcp_servers

    agents = tmp_path / "agents"
    agents.mkdir()
    (agents / "kirocrew.json").write_text(
        json.dumps(
            {
                "name": "kirocrew",
                "mcpServers": {
                    "kirocrew-core": {"command": "raw.exe", "args": []},
                    "grafana": {"command": "g", "args": []},
                },
            }
        ),
        encoding="utf-8",
    )
    overlay = tmp_path / "overlay"
    overlay.mkdir()
    (overlay / "kirocrew.json").write_text(
        json.dumps(
            {
                "name": "kirocrew",
                "mcpServers": {
                    "kirocrew-core": {
                        "command": "stub.exe",
                        "args": ["-m", "kiro_crew.mcp_gateway.stub"],
                        "_kirocrew_mcp_gateway_wrapped": True,
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("cursor_crew_bridge.agent_mcp.agents_dir", lambda: agents)
    monkeypatch.setattr("cursor_crew_bridge.agent_mcp.gateway_overlay_dir", lambda: overlay)
    servers = resolved_mcp_servers(
        "kirocrew",
        [{"name": "kirocrew-core", "command": "crew-stub.exe", "args": ["--id"]}],
    )
    by_name = {item["name"]: item for item in servers}
    assert by_name["kirocrew-core"]["command"] == "crew-stub.exe"
    assert by_name["grafana"]["command"] == "g"
    overlay_only = resolved_mcp_servers("kirocrew", [])
    assert {item["name"]: item["command"] for item in overlay_only}["kirocrew-core"] == "stub.exe"


def test_stage6_isolated_child_compact_usage_steer_and_plan(tmp_path, monkeypatch) -> None:
    """Isolated Crew↔bridge child: compact completed, 256k, no novel, plan text only."""
    import asyncio
    import json

    from cursor_crew_bridge.acp_bridge import AcpBridge
    from cursor_crew_bridge.native_parity import (
        ASK_USER_QUESTION_TITLE,
        COMPACTION_COMPLETED_SUMMARY,
        CREW_REPLAY_CLOSE,
        CREW_REPLAY_OPEN,
        CURSOR_RPC_DELTA,
        PLAN_FOOTER,
    )

    log = tmp_path / "isolated.jsonl"
    log.write_text(
        json.dumps({"role": "user", "content": "EARLY isolated goal"}) + "\n"
        + json.dumps({"role": "assistant", "content": "✅ Stage 1 complete"}) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("CURSOR_CREW_SESSION_LOG", str(log))
    before = log.read_text(encoding="utf-8")

    bridge = AcpBridge("kirocrew")
    crew: list[dict] = []
    cursor: list[dict] = []

    async def send_crew(msg: dict) -> None:
        crew.append(msg)

    async def send_cursor(msg: dict, **_kwargs) -> None:
        cursor.append(bridge._bind_cursor_session(msg))

    async def cursor_rpc(method: str, params: dict, *, timeout: float = 30) -> dict:
        if method == "session/new":
            return {"jsonrpc": "2.0", "id": 1, "result": {"sessionId": "cursor-iso"}}
        return {"jsonrpc": "2.0", "id": 2, "result": {"stopReason": "end_turn"}}

    bridge._send_crew = send_crew  # type: ignore[method-assign]
    bridge._send_cursor = send_cursor  # type: ignore[method-assign]
    bridge._cursor_rpc = cursor_rpc  # type: ignore[method-assign]

    tail = CREW_REPLAY_OPEN + "\nAssistant: Stage 5: Матрица дыр\n" + CREW_REPLAY_CLOSE
    plan_text = "This is Autopilot. Plan the remaining work."
    stage_text = tail + "\nExecute Stage 6 of 7 now. ping"

    async def run() -> None:
        await bridge._handle_crew_request(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-08-22",
                    "clientCapabilities": {"fs": {}, "terminal": False},
                },
            }
        )
        await bridge._handle_crew_request(
            {"jsonrpc": "2.0", "id": 2, "method": "session/new", "params": {"cwd": str(tmp_path)}}
        )
        await bridge._handle_cursor_response(
            {"jsonrpc": "2.0", "id": 2, "result": {"sessionId": "sid-iso"}},
            set(),
        )
        await bridge._handle_crew_request(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "session/set_mode",
                "params": {"sessionId": "sid-iso", "modeId": "kirocrew"},
            }
        )
        await bridge._handle_crew_request(
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "session/prompt",
                "params": {
                    "sessionId": "sid-iso",
                    "prompt": [{"type": "text", "text": stage_text}],
                },
            }
        )
        await bridge._handle_crew_request(
            {
                "jsonrpc": "2.0",
                "id": 5,
                "method": "session/prompt",
                "params": {
                    "sessionId": "sid-iso",
                    "prompt": [{"type": "text", "text": plan_text}],
                },
            }
        )
        await bridge._handle_cursor_message(
            {
                "jsonrpc": "2.0",
                "id": 40,
                "method": "cursor/create_plan",
                "params": {"sessionId": "sid-iso", "plan": "secret-plan-body"},
            }
        )
        await bridge._handle_crew_request(
            {
                "jsonrpc": "2.0",
                "id": 6,
                "method": "session/prompt",
                "params": {
                    "sessionId": "sid-iso",
                    "prompt": [{"type": "text", "text": "/compact keep the thread"}],
                },
            }
        )
        await bridge._handle_crew_request(
            {
                "jsonrpc": "2.0",
                "id": 7,
                "method": "_kiro.dev/compaction/status",
                "params": {"sessionId": "sid-iso"},
            }
        )
        await bridge._handle_cursor_message(
            {
                "jsonrpc": "2.0",
                "id": 50,
                "method": "cursor/ask_question",
                "params": {
                    "sessionId": "cursor-iso",
                    "questions": [
                        {
                            "prompt": "Still alive?",
                            "options": [{"id": "yes", "label": "Yes"}],
                        }
                    ],
                },
            }
        )
        await bridge._handle_cursor_message(
            {
                "jsonrpc": "2.0",
                "id": 51,
                "method": "session/request_permission",
                "params": {
                    "sessionId": "cursor-iso",
                    "options": [{"optionId": "allow-once", "name": "Allow once"}],
                },
            }
        )

    asyncio.run(run())

    usage = [
        item
        for item in crew
        if (item.get("params") or {}).get("update", {}).get("sessionUpdate") == "usage_update"
    ]
    assert usage
    assert all(item["params"]["update"]["size"] == 256_000 for item in usage)
    assert usage[0]["params"]["sessionId"] == "sid-iso"

    prompts = [item for item in cursor if item.get("method") == "session/prompt"]
    assert len(prompts) == 2
    stage_fwd = "\n".join(block.get("text", "") for block in prompts[0]["params"]["prompt"])
    assert CURSOR_RPC_DELTA.split("\n", 1)[0] in stage_fwd
    assert "Write stage_N_result.md" not in stage_fwd
    assert "_capture_stage_result" in stage_fwd
    assert "cursor/create_plan" in stage_fwd
    assert PLAN_FOOTER in stage_fwd
    assert "spawn_run" in stage_fwd
    assert "EARLY isolated goal" in stage_fwd
    assert "Матрица дыр" not in stage_fwd
    assert "stage execution" not in stage_fwd

    plan_fwd = "\n".join(block.get("text", "") for block in prompts[1]["params"]["prompt"])
    assert "This is Autopilot. Plan the remaining work." in plan_fwd
    assert plan_fwd.count("[KIRO CREW — Cursor ACP delta]") == 0
    assert "Write stage_N_result.md" not in plan_fwd
    assert not any(item.get("method") == "cursor/create_plan" for item in cursor)

    plan_rpc = next(item for item in cursor if item.get("id") == 40)
    assert plan_rpc["result"]["outcome"]["outcome"] == "accepted"
    assert not any("secret-plan-body" in str(item) for item in crew)

    notes = [item for item in crew if item.get("method") == "_kiro.dev/compaction/status"]
    assert notes and notes[0]["params"]["status"]["type"] == "completed"
    assert notes[0]["params"]["summary"] == COMPACTION_COMPLETED_SUMMARY
    assert notes[0]["params"]["sessionId"] == "sid-iso"
    assert bridge._session_id == "sid-iso"
    assert bridge._cursor_sid == "cursor-iso"
    ended = next(item for item in crew if item.get("id") == 6)
    assert ended["result"]["stopReason"] == "end_turn"
    poll = next(item for item in crew if item.get("id") == 7)
    assert poll["result"]["supported"] is True
    assert usage[-1]["params"]["update"]["used"] < 95_000
    assert log.read_text(encoding="utf-8") == before

    mode_ack = next(item for item in crew if item.get("id") == 3)
    assert mode_ack["result"]["modes"]["currentModeId"] == "kirocrew"
    assert not any(item.get("method") == "session/set_mode" for item in cursor)
    cards = [
        item
        for item in crew
        if (item.get("params") or {}).get("update", {}).get("title") == ASK_USER_QUESTION_TITLE
    ]
    assert cards
    perms = [item for item in crew if item.get("method") == "session/request_permission"]
    assert perms


def test_resolved_mcp_ignores_settings_mcp_json(tmp_path, monkeypatch) -> None:
    from cursor_crew_bridge.agent_mcp import resolved_mcp_servers

    agents = tmp_path / "agents"
    agents.mkdir()
    (agents / "kirocrew.json").write_text(
        json.dumps(
            {
                "name": "kirocrew",
                "mcpServers": {"kirocrew-core": {"command": "core.exe", "args": []}},
            }
        ),
        encoding="utf-8",
    )
    settings = tmp_path / "settings"
    settings.mkdir()
    (settings / "mcp.json").write_text(
        json.dumps({"mcpServers": {"extra-noise": {"command": "noise.exe", "args": []}}}),
        encoding="utf-8",
    )
    monkeypatch.setattr("cursor_crew_bridge.agent_mcp.agents_dir", lambda: agents)
    monkeypatch.setattr("cursor_crew_bridge.agent_mcp.gateway_overlay_dir", lambda: tmp_path / "missing-overlay")
    names = {item["name"] for item in resolved_mcp_servers("kirocrew", [])}
    assert names == {"kirocrew-core"}
    assert "extra-noise" not in names


def test_session_new_emits_mcp_initialized(monkeypatch) -> None:
    import asyncio

    from cursor_crew_bridge.acp_bridge import AcpBridge

    monkeypatch.setattr("cursor_crew_bridge.acp_bridge.skip_mcp", lambda: False)
    monkeypatch.setattr(
        "cursor_crew_bridge.agent_mcp.mcp_servers_for_acp",
        lambda agent: [{"name": "kirocrew-core", "command": "core.exe", "args": [], "env": []}],
    )
    monkeypatch.setattr("cursor_crew_bridge.agent_mcp.overlay_mcp_servers", lambda agent: [])
    monkeypatch.setattr("cursor_crew_bridge.acp_bridge.prepare_cwd", lambda cwd: cwd or ".")

    bridge = AcpBridge("kirocrew")
    crew: list[dict] = []
    cursor: list[dict] = []

    async def send_crew(msg: dict) -> None:
        crew.append(msg)

    async def send_cursor(msg: dict, **_kwargs) -> None:
        cursor.append(msg)

    bridge._send_crew = send_crew  # type: ignore[method-assign]
    bridge._send_cursor = send_cursor  # type: ignore[method-assign]

    async def run() -> None:
        await bridge._handle_crew_request(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "session/new",
                "params": {"cwd": ".", "mcpServers": []},
            }
        )
        await bridge._handle_cursor_response(
            {"jsonrpc": "2.0", "id": 1, "result": {"sessionId": "sid-mcp"}},
            set(),
        )

    asyncio.run(run())
    inits = [item for item in crew if item.get("method") == "_kiro.dev/mcp/server_initialized"]
    assert inits
    assert inits[0]["params"]["serverName"] == "kirocrew-core"
    assert inits[0]["params"]["sessionId"] == "sid-mcp"
    cmds = [item for item in crew if item.get("method") == "_kiro.dev/commands/available"]
    assert cmds
    names = {item["name"] for item in cmds[0]["params"]["commands"]}
    assert {"compact", "help", "tools", "usage"} <= names
    acp_cmds = [
        item
        for item in crew
        if (item.get("params") or {}).get("update", {}).get("sessionUpdate") == "available_commands_update"
    ]
    assert acp_cmds


def test_commands_options_rpc_returns_options() -> None:
    import asyncio

    from cursor_crew_bridge.acp_bridge import AcpBridge

    bridge = AcpBridge("kirocrew")
    crew: list[dict] = []

    async def send_crew(msg: dict) -> None:
        crew.append(msg)

    bridge._send_crew = send_crew  # type: ignore[method-assign]

    async def run() -> None:
        await bridge._handle_crew_request(
            {
                "jsonrpc": "2.0",
                "id": 9,
                "method": "_kiro.dev/commands/options",
                "params": {"sessionId": "sid-opt", "command": "compact", "partial": ""},
            }
        )

    asyncio.run(run())
    ack = next(item for item in crew if item.get("id") == 9)
    assert ack["result"]["options"]
    assert ack["result"]["hasMore"] is False
    assert ack["result"]["options"][0]["value"] == "compact"


def test_normalize_update_stamps_shell_kind() -> None:
    msg = _normalize_update(
        {
            "jsonrpc": "2.0",
            "method": "session/update",
            "params": {
                "sessionId": "sid-sh",
                "update": {
                    "sessionUpdate": "tool_call",
                    "toolCallId": "t-sh",
                    "title": "Shell",
                    "kind": "shell",
                    "rawInput": {"command": "ls"},
                },
            },
        }
    )
    update = msg["params"]["update"]
    assert update["kind"] == "execute"
    assert update["_meta"]["kiro"]["toolName"] == "execute_bash"
