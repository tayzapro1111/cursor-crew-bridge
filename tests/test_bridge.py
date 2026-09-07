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
    text = _ask_question_text(params)
    assert "Which stage?" in text
    assert "Stage 3" in text


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
    assert rows[0]["context_window_tokens"] == 256_000


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
    from cursor_crew_bridge.config import BRIDGE_VERSION

    bridge = AcpBridge("kirocrew")
    crew: list[dict] = []
    cursor: list[dict] = []

    async def send_crew(msg: dict) -> None:
        crew.append(msg)

    async def send_cursor(msg: dict) -> None:
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
    assert init["result"]["serverInfo"]["version"] == BRIDGE_VERSION

    forwarded = next(item for item in cursor if item.get("method") == "session/prompt")
    texts = [block.get("text", "") for block in forwarded["params"]["prompt"]]
    assert any("stage execution" in text for text in texts)


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

    async def send_cursor(msg: dict) -> None:
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
