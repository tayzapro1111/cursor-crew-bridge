import json
import re

from cursor_crew_bridge.native_parity import (
    ADVERTISE_LOAD_SESSION,
    ASK_USER_QUESTION_TITLE,
    COMPACTION_COMPLETED_SUMMARY,
    COMPACTION_FAILED_SUMMARY,
    COMPACT_SEED_PREFACE,
    CREW_REPLAY_CLOSE,
    CREW_REPLAY_OPEN,
    REPLAY_THREAD_PREFACE,
    CREATE_PLAN_MAPPING,
    CREATE_PLAN_OUTCOME,
    CURSOR_EXTRAS,
    MEMORY_CHANNELS,
    AGENT_PROMPT_MARK,
    PLAN_FOOTER,
    PLAN_HEADER,
    CURSOR_RPC_DELTA,
    PLAN_TEMPLATE,
    REPLAY_ROLES,
    REPLAY_SKIP_ROLES,
    UsageTracker,
    build_compact_summary,
    load_conversation_rows,
    replace_crew_replay_block,
    rewrite_prompt_history,
    compact_prompt_hint,
    compaction_completed_notification,
    compaction_failed_notification,
    compaction_status_ack,
    conversation_log_stem,
    cursor_prompt_used_tokens,
    cursor_todos_crew_messages,
    cursor_todos_snapshot,
    drop_update_after_cancel,
    enrich_cursor_tool_update,
    estimate_tokens,
    execute_command_name,
    is_compact_command,
    is_compact_prompt,
    last_prompt_block,
    local_slash_crew_messages,
    local_slash_reply,
    slash_command_name,
    is_stage_execution,
    looks_like_orchestrator,
    normalize_fs_path,
    prepend_prompt_blocks,
    prompt_cancelled_result,
    prompt_end_turn_result,
    remember_orchestrator,
    session_cancel_notification,
    session_load_error,
    steering_texts,
    usage_update_message,
    ORCHESTRATOR_MARK,
    crew_client_capabilities,
    cursor_load_session_supported,
    cursor_prompt_capabilities,
    current_mode_update_message,
    stamp_kiro_tool_meta,
    commands_available_notification,
    available_commands_update_message,
    command_options_result,
)


def test_estimate_tokens_is_chars_over_four() -> None:
    assert estimate_tokens(0) == 0
    assert estimate_tokens(4) == 1
    assert estimate_tokens(8000) == 2000


def test_usage_tracker_uses_max_not_sum_of_prompts() -> None:
    tracker = UsageTracker(window=256_000)
    tracker.note_prompt_chars(8000)
    first = tracker.used
    tracker.note_prompt_chars(8000)
    assert tracker.used == first
    tracker.note_output_chars(400)
    assert tracker.used > first
    tracker.note_cursor_used(12_000)
    assert tracker.used == 12_000


def test_current_mode_update_shape() -> None:
    msg = current_mode_update_message("sid-1", "kirocrew")
    update = msg["params"]["update"]
    assert msg["method"] == "session/update"
    assert update["sessionUpdate"] == "current_mode_update"
    assert update["currentModeId"] == "kirocrew"


def test_usage_update_shape_matches_crew_parse() -> None:
    msg = usage_update_message("sid-1", 180_000, 256_000)
    update = msg["params"]["update"]
    assert msg["method"] == "session/update"
    assert update["sessionUpdate"] == "usage_update"
    assert update["used"] == 180_000
    assert update["size"] == 256_000


def test_usage_update_ignores_cursor_one_million_size() -> None:
    msg = usage_update_message("sid-1", 80_000, 1_000_000)
    update = msg["params"]["update"]
    assert update["size"] == 256_000
    assert update["used"] == 80_000
    pct = round(update["used"] / update["size"] * 100, 1)
    assert 30 <= pct <= 32
    assert abs(80_000 / 1_000_000 * 100 - 8.0) < 0.1


def test_usage_tracker_synthesizes_replay_occupancy_on_256k() -> None:
    tracker = UsageTracker()
    tracker.note_prompt_chars(80_359)
    used, window = tracker.snapshot()
    assert window == 256_000
    assert used == 80_359 // 4
    pct = used / window * 100
    assert 7 < pct < 9
    assert used / 1_000_000 * 100 < 3


def test_crew_plan_regex_accepts_template() -> None:
    header = re.compile(r"📋\s*Plan for:", re.IGNORECASE)
    stage = re.compile(r"^Stage\s+(\d+)\s*:", re.MULTILINE | re.IGNORECASE)
    option = re.compile(r"\[OPTION:\s*Go\s*\|.*Cancel\s*\]")
    text = PLAN_TEMPLATE.replace("<task description>", "Autopilot 1:1")
    assert header.search(text)
    assert stage.findall(text) == ["1", "2", "N"] or "Stage 1:" in text
    assert option.search(text)
    assert PLAN_HEADER in text
    assert PLAN_FOOTER in text
    assert text.strip().endswith(PLAN_FOOTER)


def test_stage_and_orchestrator_detection() -> None:
    stage = 'Execute Stage 4 of 8 now. When you have fully completed all work'
    assert is_stage_execution(stage)
    assert looks_like_orchestrator("Switch to Autopilot mode? OK")
    assert looks_like_orchestrator("hello", crew_mode="orchestrator")
    assert looks_like_orchestrator("🎯 Goal: Fable parity\nPlan Status:")
    assert not looks_like_orchestrator("just a bugfix")


def test_steering_plan_then_stage() -> None:
    already: set[str] = set()
    plan_params = {"prompt": [{"type": "text", "text": "This is Autopilot. Make a plan."}]}
    first = steering_texts(plan_params, agent="kirocrew", crew_mode="", already=already)
    blob = "\n".join(first)
    assert ORCHESTRATOR_MARK in blob
    assert "cursor/create_plan" in blob
    assert "host" in already
    stage_params = {"prompt": [{"type": "text", "text": "Execute Stage 1 of 3 now."}]}
    second = steering_texts(stage_params, agent="kirocrew", crew_mode="orchestrator", already=already)
    assert second == []
    third = steering_texts(stage_params, agent="kirocrew", crew_mode="orchestrator", already=already)
    assert third == []


def test_midchat_latch_keeps_planning_steer() -> None:
    assert remember_orchestrator("Execute Stage 1 of 3 now.", "kirocrew") == "orchestrator"
    assert remember_orchestrator("plain bugfix", "kirocrew") == "kirocrew"
    assert remember_orchestrator("plain bugfix", "orchestrator") == "orchestrator"
    already = {"host"}
    later = {"prompt": [{"type": "text", "text": "now fix the remaining callers"}]}
    cwd = str(__import__("pathlib").Path(".").resolve())
    extras = steering_texts(
        later, agent="kirocrew", crew_mode="orchestrator", already=already, cwd=cwd
    )
    blob = "\n".join(extras)
    assert ORCHESTRATOR_MARK in blob
    assert "host-orchestrator" in already
    again = steering_texts(
        later, agent="kirocrew", crew_mode="orchestrator", already=already, cwd=cwd
    )
    assert again == []
    plain = steering_texts(later, agent="kirocrew", crew_mode="kirocrew", already=already)
    assert plain == []


def test_planning_steer_matches_orchestrator_contract() -> None:
    assert PLAN_FOOTER in CURSOR_RPC_DELTA
    assert "cursor/create_plan" in CURSOR_RPC_DELTA
    assert "stage_N_result.md" in CURSOR_RPC_DELTA
    assert "_capture_stage_result" in CURSOR_RPC_DELTA
    assert "cursor/task" in CURSOR_RPC_DELTA
    assert "Write stage_N_result.md" not in CURSOR_RPC_DELTA


def test_lite_agent_is_not_steered() -> None:
    params = {"prompt": [{"type": "text", "text": "This is Autopilot."}]}
    assert steering_texts(params, agent="kirocrew-lite", crew_mode="orchestrator", already=set()) == []


def test_prepend_keeps_user_block() -> None:
    params = {"prompt": [{"type": "text", "text": "user"}], "sessionId": "s"}
    out = prepend_prompt_blocks(params, ["STEER"])
    assert out["prompt"][0]["text"].startswith("STEER")
    assert out["prompt"][-1]["text"] == "user"


def test_session_load_error_is_jsonrpc() -> None:
    err = session_load_error()
    assert err["code"] == -32001
    assert "replay" in err["message"]
    assert ADVERTISE_LOAD_SESSION is False


def test_replay_and_memory_contract() -> None:
    assert REPLAY_ROLES == frozenset({"user", "assistant", "inject"})
    assert "thought" in REPLAY_SKIP_ROLES
    assert "tool" in REPLAY_SKIP_ROLES
    assert MEMORY_CHANNELS["embeddings"] == "out_of_bridge"
    assert MEMORY_CHANNELS["kiro_q"] == "absent"
    assert MEMORY_CHANNELS["memory_lessons"] == "crew_first_prompt"


def test_compact_prompt_and_failed_notification() -> None:
    assert is_compact_prompt("/compact")
    assert is_compact_prompt("  /compact Preserve this session context")
    assert not is_compact_prompt("please compact the logs")
    assert not is_compact_prompt("")
    assert is_compact_command({"command": {"command": "compact", "args": {}}})
    assert is_compact_command({"command": "/compact"})
    assert not is_compact_command({"command": {"command": "help"}})
    ack = compaction_status_ack()
    assert ack["status"] == "idle"
    assert ack["supported"] is True
    note = compaction_failed_notification("sid-c")
    assert note["method"] == "_kiro.dev/compaction/status"
    assert "id" not in note
    assert note["params"]["status"]["type"] == "failed"
    assert note["params"]["status"]["error"] == COMPACTION_FAILED_SUMMARY
    assert note["params"]["summary"] == COMPACTION_FAILED_SUMMARY
    assert note["params"]["sessionId"] == "sid-c"
    done = compaction_completed_notification("sid-c")
    assert done["params"]["status"]["type"] == "completed"
    assert done["params"]["summary"] == COMPACTION_COMPLETED_SUMMARY
    assert done["params"]["sessionId"] == "sid-c"
    assert compact_prompt_hint("/compact Preserve this session context") == "Preserve this session context"
    assert conversation_log_stem("dashboard:chat-6-1") == "dashboard_chat-6-1"
    ended = prompt_end_turn_result(9)
    assert ended["result"]["stopReason"] == "end_turn"

def test_local_slash_commands() -> None:
    assert slash_command_name("/help") == "help"
    assert slash_command_name("  /tools  ") == "tools"
    assert slash_command_name("/usage") == "usage"
    assert slash_command_name("/context") == "context"
    assert slash_command_name("/clear") == "clear"
    assert slash_command_name("/compact") == ""
    assert slash_command_name("/help me write a test") == ""
    assert slash_command_name("help") == ""
    assert last_prompt_block({"prompt": [{"type": "text", "text": "history"}, {"type": "text", "text": "/usage"}]}) == "/usage"
    assert slash_command_name(last_prompt_block({"prompt": [{"type": "text", "text": "inject"}, {"type": "text", "text": "/usage"}]})) == "usage"
    assert execute_command_name({"command": {"command": "help", "args": {}}}) == "help"
    assert execute_command_name({"command": "/tools"}) == "tools"
    help_text = local_slash_reply("help") or ""
    assert "/compact" in help_text
    assert "/usage" in help_text
    tools_text = local_slash_reply("tools") or ""
    assert "fs_read" in tools_text
    usage_text = local_slash_reply("usage", used=19_916, window=256_000) or ""
    assert "19,916" in usage_text
    assert "256,000" in usage_text
    assert "Kiro credits" in usage_text
    assert local_slash_reply("compact") is None
    frames = local_slash_crew_messages("sid-h", help_text)
    assert frames[0]["method"] == "session/update"
    assert frames[0]["params"]["update"]["sessionUpdate"] == "agent_message_chunk"


def test_compact_summary_keeps_early_users_not_80k_tail() -> None:
    early = "EARLY_GOAL bind cursor-crew 1:1 without 8% reset"
    late = "LATE_TAIL " + ("x" * 90_000)
    rows = [
        {"role": "user", "content": early},
        {"role": "assistant", "content": "✅ Stage 1 complete\n" + ("noise " * 200)},
        {"role": "inject", "content": "AUTOPILOT stage 4"},
        {"role": "user", "content": late},
        {"role": "assistant", "content": "Stage 5: Матрица дыр " + ("y" * 2000)},
    ]
    summary = build_compact_summary(rows, budget=12_000)
    assert COMPACT_SEED_PREFACE in summary
    assert early in summary
    assert "LATE_TAIL" in summary
    assert "✅ Stage 1 complete" in summary
    assert "Stage 5: Матрица дыр" in summary
    assert "AUTOPILOT stage 4" in summary
    assert len(summary) <= 12_000
    assert late not in summary


def test_compact_summary_uses_tool_facts_not_raw_payload() -> None:
    raw = "🔧 Read D:\\bridge\\native_parity.py\n" + ("SECRET_BLOB " * 400)
    rows = [
        {"role": "user", "content": "EARLY keep me"},
        {"role": "tool", "content": raw},
        {"role": "thought", "content": "do not dump this thought"},
    ]
    summary = build_compact_summary(rows, preface=REPLAY_THREAD_PREFACE)
    assert REPLAY_THREAD_PREFACE in summary
    assert "EARLY keep me" in summary
    assert "native_parity.py" in summary
    assert "SECRET_BLOB" not in summary
    assert "do not dump this thought" not in summary


def test_replace_crew_replay_block_swaps_tail() -> None:
    early = "User: EARLY_GOAL bind 1:1"
    tail = "Assistant: Stage 5: Матрица дыр\n" + ("z" * 1000)
    text = (
        "[SESSION CONTEXT]\n"
        + CREW_REPLAY_OPEN
        + "\n"
        + tail
        + "\n"
        + CREW_REPLAY_CLOSE
        + "\nCURRENT USER REQUEST\n"
    )
    thread = REPLAY_THREAD_PREFACE + early + "\n"
    out = replace_crew_replay_block(text, thread)
    assert out is not None
    assert early in out
    assert CREW_REPLAY_OPEN in out
    assert CREW_REPLAY_CLOSE in out
    assert "CURRENT USER REQUEST" in out
    assert "Матрица дыр" not in out
    params, replaced = rewrite_prompt_history(
        {"prompt": [{"type": "text", "text": text}]},
        thread,
    )
    assert replaced is True
    assert early in params["prompt"][0]["text"]
    assert "Матрица дыр" not in params["prompt"][0]["text"]


def test_load_conversation_rows_skips_thoughts_and_dedupes_tools(tmp_path) -> None:
    log = tmp_path / "slot.jsonl"
    import json

    lines = [
        {"role": "user", "content": "hello-early"},
        {"role": "thought", "content": "secret-thought"},
        {"role": "tool", "content": "🔧 Read foo.py\n" + ("DUMP " * 200)},
        {"role": "tool", "content": "🔧 Read foo.py\nmore dump"},
        {"role": "tool", "content": "🔧 Edit bar.py"},
        {"role": "assistant", "content": "✅ done"},
    ]
    log.write_text("".join(json.dumps(row) + "\n" for row in lines), encoding="utf-8")
    rows = load_conversation_rows(log)
    roles = [row["role"] for row in rows]
    assert roles.count("user") == 1
    assert "thought" not in roles
    tools = [row["content"] for row in rows if row["role"] == "tool"]
    assert tools == ["🔧 Read foo.py", "🔧 Edit bar.py"]
    assert all("DUMP" not in row["content"] for row in rows)


def test_cursor_prompt_tokens() -> None:
    assert cursor_prompt_used_tokens({"stopReason": "end_turn"}) is None
    assert cursor_prompt_used_tokens({"inputTokens": 1000, "outputTokens": 50}) == 1050
    assert cursor_prompt_used_tokens({"usage": {"totalTokens": 4096}}) == 4096
    assert cursor_prompt_used_tokens({"usage": {"promptTokens": 80, "completionTokens": 20}}) == 100


def test_cancel_is_notification_not_request() -> None:
    frame = session_cancel_notification("sid-9")
    assert frame["method"] == "session/cancel"
    assert "id" not in frame
    assert frame["params"]["sessionId"] == "sid-9"
    result = prompt_cancelled_result(17)
    assert result["id"] == 17
    assert result["result"]["stopReason"] == "cancelled"
    assert drop_update_after_cancel("agent_message_chunk")
    assert drop_update_after_cancel("tool_call")
    assert not drop_update_after_cancel("usage_update")


def test_cursor_todos_become_kiro_todo_list() -> None:
    snap = cursor_todos_snapshot(
        {
            "todos": [
                {"id": "a", "content": "Read sources", "status": "completed"},
                {"id": "b", "text": "Write fix", "status": "in_progress"},
            ]
        }
    )
    assert snap is not None
    assert snap["tasks"][0]["completed"] is True
    assert snap["tasks"][1]["completed"] is False
    assert snap["tasks"][1]["task_description"] == "Write fix"
    frames = cursor_todos_crew_messages("sid-1", {"todos": [{"content": "One"}]})
    assert len(frames) == 2
    assert frames[0]["params"]["update"]["_meta"]["kiro"]["toolName"] == "todo_list"
    assert frames[1]["params"]["update"]["rawOutput"]["tasks"][0]["task_description"] == "One"


def test_enrich_edit_backtick_path() -> None:
    path = r"D:\Razrabotka\vpnsite\shutdown-fyi\web\src\styles\global.css"
    out = enrich_cursor_tool_update(
        {
            "sessionUpdate": "tool_call_update",
            "toolCallId": "call-36",
            "title": f"Edit `{path}`",
        }
    )
    assert out["title"] == "Editing global.css"
    assert out["kind"] == "edit"
    assert out["rawInput"]["path"] == normalize_fs_path(path)
    assert "\\" not in out["rawInput"]["path"]
    assert out["toolCallId"] == "call-36"


def test_enrich_edit_file_from_locations() -> None:
    path = r"D:\Razrabotka\vpnsite\shutdown-fyi\web\src\components\Widget.astro"
    out = enrich_cursor_tool_update(
        {
            "sessionUpdate": "tool_call",
            "kind": "edit",
            "title": "Edit File",
            "locations": [{"path": path}],
        }
    )
    assert out["title"] == "Editing Widget.astro"
    assert out["rawInput"]["path"] == normalize_fs_path(path)
    assert out["kind"] == "edit"


def test_enrich_keeps_existing_raw_input_fields() -> None:
    path = r"C:\proj\a.ts"
    out = enrich_cursor_tool_update(
        {
            "sessionUpdate": "tool_call_update",
            "title": f"Edit `{path}`",
            "rawInput": {"old_string": "a", "new_string": "b"},
        }
    )
    assert out["rawInput"]["old_string"] == "a"
    assert out["rawInput"]["path"] == normalize_fs_path(path)


def test_enrich_leaves_read_and_empty_status() -> None:
    read = {
        "sessionUpdate": "tool_call_update",
        "title": r"Read C:\Users\admin\.cursor\skills\fable-close-loop\SKILL.md",
        "kind": None,
    }
    assert enrich_cursor_tool_update(read) is read
    empty = {
        "sessionUpdate": "tool_call_update",
        "toolCallId": "call-36",
        "title": "",
        "status": "in_progress",
    }
    assert enrich_cursor_tool_update(empty) is empty
    grep = {
        "sessionUpdate": "tool_call",
        "kind": "search",
        "title": "Find `**/*.{astro,css}`",
    }
    assert enrich_cursor_tool_update(grep) is grep


def test_enrich_does_not_merge_distinct_edit_ids() -> None:
    path = r"D:\Razrabotka\vpnsite\shutdown-fyi\web\src\styles\global.css"
    first = enrich_cursor_tool_update(
        {"sessionUpdate": "tool_call", "toolCallId": "call-a", "kind": "edit", "title": f"Edit `{path}`"}
    )
    second = enrich_cursor_tool_update(
        {"sessionUpdate": "tool_call", "toolCallId": "call-b", "kind": "edit", "title": f"Edit `{path}`"}
    )
    assert first["toolCallId"] == "call-a"
    assert second["toolCallId"] == "call-b"
    assert first["title"] == second["title"] == "Editing global.css"


def test_cursor_extras_contract() -> None:
    assert CREATE_PLAN_MAPPING == "wont"
    assert CREATE_PLAN_OUTCOME["outcome"]["outcome"] == "accepted"
    assert CURSOR_EXTRAS["ask_question"] == "crew_card"
    assert CURSOR_EXTRAS["create_plan"] == "wont"
    assert CURSOR_EXTRAS["update_todos"] == "todo_list"
    assert CURSOR_EXTRAS["task"] == "thought"
    assert CURSOR_EXTRAS["generate_image"] == "image_or_ref"
    assert CURSOR_EXTRAS["session_new_mcp"] == "incoming_stub_wins"


def test_cursor_ask_payload_matches_crew_card() -> None:
    from cursor_crew_bridge.native_parity import (
        cursor_ask_crew_messages,
        cursor_ask_crew_payload,
        cursor_ask_result,
    )

    params = {
        "questions": [
            {
                "id": "q1",
                "prompt": "Which stage?",
                "header": "SCOPE",
                "options": [
                    {"id": "a", "label": "Stage 3", "description": "keep going"},
                    {"id": "b", "label": "Stop"},
                ],
            }
        ]
    }
    payload = cursor_ask_crew_payload(params)
    assert payload is not None
    assert "description" not in payload
    question = payload["questions"][0]
    assert question["question"] == "Which stage?"
    assert question["header"] == "SCOPE"
    assert question["options"][0]["label"] == "Stage 3"
    assert question["options"][0]["description"] == "keep going"
    assert question["multiSelect"] is False
    frames = cursor_ask_crew_messages("sid-q", params)
    update = frames[0]["params"]["update"]
    assert update["title"] == ASK_USER_QUESTION_TITLE
    assert update["sessionUpdate"] == "tool_call"
    assert update["rawInput"] == payload
    assert "description" not in update["rawInput"]
    assert cursor_ask_result()["outcome"]["outcome"] == "skipped"
    assert cursor_ask_crew_payload({"questions": [{"prompt": "No options"}]}) is None


def test_cursor_ask_payload_passes_crew_validator() -> None:
    import sys
    from pathlib import Path

    from cursor_crew_bridge.native_parity import cursor_ask_crew_payload

    crew_src = Path(r"D:\Razrabotka\cursor-crew-bridge\KiroCrew-0.5.0\src")
    assert crew_src.is_dir()
    sys.path.insert(0, str(crew_src))
    from kiro_crew.acp._dispatch import select_tool_title
    from kiro_crew.validation import validate_ask_user_question

    payload = cursor_ask_crew_payload(
        {
            "questions": [
                {
                    "prompt": "Pick a path",
                    "header": "SCOPE",
                    "options": [{"label": "Keep"}, {"label": "Stop"}],
                }
            ]
        }
    )
    assert payload is not None
    validated = validate_ask_user_question(payload)
    assert validated[0]["question"] == "Pick a path"
    assert validated[0]["options"][0]["label"] == "Keep"
    assert (
        select_tool_title(ASK_USER_QUESTION_TITLE, payload, "other")
        == ASK_USER_QUESTION_TITLE
    )
    stolen = dict(payload)
    stolen["description"] = "would steal the pill"
    assert select_tool_title(ASK_USER_QUESTION_TITLE, stolen, "other") == "would steal the pill"


def test_cursor_task_and_image_helpers() -> None:
    from cursor_crew_bridge.native_parity import (
        cursor_task_crew_messages,
        extract_generated_image,
        extract_generated_image_ref,
        generated_image_crew_messages,
    )

    thought = cursor_task_crew_messages("sid-t", {"description": "Investigating MCP merge"})
    assert thought[0]["params"]["update"]["sessionUpdate"] == "agent_thought_chunk"
    assert "Investigating MCP merge" in thought[0]["params"]["update"]["content"]["text"]

    block = extract_generated_image(
        {"type": "image", "mimeType": "image/png", "data": "AAA"}
    )
    assert block == {"type": "image", "data": "AAA", "mimeType": "image/png"}
    assert extract_generated_image_ref({"url": "https://cdn.example/x.png"}) == "https://cdn.example/x.png"
    url_frames = generated_image_crew_messages("sid-i", {"url": "https://cdn.example/x.png"})
    assert url_frames[0]["params"]["update"]["content"]["type"] == "text"
    assert "https://cdn.example/x.png" in url_frames[0]["params"]["update"]["content"]["text"]
    b64_frames = generated_image_crew_messages(
        "sid-i", {"type": "image", "mimeType": "image/png", "data": "BBB"}
    )
    assert b64_frames[0]["params"]["update"]["content"]["type"] == "image"


def test_host_identity_and_native_orchestrator_file() -> None:
    already: set[str] = set()
    params = {"prompt": [{"type": "text", "text": "This is Autopilot. Make a plan."}]}
    extras = steering_texts(
        params,
        agent="kirocrew",
        crew_mode="",
        already=already,
        cwd=str(__import__("pathlib").Path(".").resolve()),
        first_turn=True,
    )
    blob = "\n".join(extras)
    assert ORCHESTRATOR_MARK in blob
    assert PLAN_HEADER in blob
    assert "spawn_run" in blob
    assert "host" in already
    assert "Fable" not in blob
    assert AGENT_PROMPT_MARK not in blob


def test_cursor_load_session_follows_child_caps() -> None:
    assert cursor_load_session_supported(None) is False
    assert cursor_load_session_supported({}) is False
    assert cursor_load_session_supported({"loadSession": True}) is True
    caps = cursor_prompt_capabilities({"promptCapabilities": {"image": True, "audio": True}})
    assert caps["image"] is True
    assert caps["audio"] is True
    assert caps["embeddedContext"] is True
    passed = crew_client_capabilities(
        {"fs": {"readTextFile": False}, "terminal": False, "elicitation": {"form": {}}}
    )
    assert passed["elicitation"] == {"form": {}}
    assert passed["fs"]["readTextFile"] is False


def test_plain_first_turn_loads_prompt_md() -> None:
    already: set[str] = set()
    extras = steering_texts(
        {"prompt": [{"type": "text", "text": "fix the remaining callers"}]},
        agent="kirocrew",
        crew_mode="kirocrew",
        already=already,
        cwd=str(__import__("pathlib").Path(".").resolve()),
        first_turn=True,
    )
    blob = "\n".join(extras)
    assert AGENT_PROMPT_MARK in blob
    assert "spawn_run" in blob
    assert "Cursor ACP delta" in blob
    assert ORCHESTRATOR_MARK not in blob


def test_dump_acp_redacts_tokens(tmp_path, monkeypatch) -> None:
    from cursor_crew_bridge.native_parity import dump_acp_frame

    dump = tmp_path / "acp-dump.jsonl"
    monkeypatch.setenv("CURSOR_CREW_DUMP", str(dump))
    dump_acp_frame(
        "crew_in",
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"accessToken": "secret-token-value", "ok": "yes"},
        },
    )
    line = dump.read_text(encoding="utf-8").strip()
    record = json.loads(line)
    assert record["dir"] == "crew_in"
    assert record["method"] == "initialize"
    assert record["params"]["accessToken"] == "<redacted>"
    assert record["params"]["ok"] == "yes"
    assert "secret-token-value" not in line


def test_stamp_kiro_tool_meta_maps_cursor_builtins() -> None:
    shell = stamp_kiro_tool_meta(
        {
            "sessionUpdate": "tool_call",
            "toolCallId": "s1",
            "title": "Shell",
            "kind": "shell",
            "rawInput": {"command": "ls"},
        }
    )
    assert shell["kind"] == "execute"
    assert shell["_meta"]["kiro"]["toolName"] == "execute_bash"
    assert "mcpServerName" not in shell["_meta"]["kiro"]
    read = stamp_kiro_tool_meta(
        {
            "sessionUpdate": "tool_call",
            "title": r"Read C:\\proj\\a.ts",
            "kind": None,
        }
    )
    assert read["kind"] == "read"
    assert read["_meta"]["kiro"]["toolName"] == "fs_read"
    grep = stamp_kiro_tool_meta(
        {
            "sessionUpdate": "tool_call",
            "kind": "search",
            "title": "Grep TODO",
        }
    )
    assert grep["_meta"]["kiro"]["toolName"] == "grep"
    mcp = stamp_kiro_tool_meta(
        {
            "sessionUpdate": "tool_call",
            "title": "mcp__kirocrew-core__spawn_run",
            "kind": "other",
        }
    )
    assert mcp["_meta"]["kiro"]["toolName"] == "spawn_run"
    assert mcp["_meta"]["kiro"]["mcpServerName"] == "kirocrew-core"
    assert mcp["title"] == "@kirocrew-core/spawn_run"
    kept = stamp_kiro_tool_meta(
        {
            "sessionUpdate": "tool_call",
            "title": "Shell",
            "kind": "shell",
            "_meta": {"kiro": {"toolName": "execute_bash"}},
        }
    )
    assert kept["_meta"]["kiro"]["toolName"] == "execute_bash"
    assert kept["kind"] == "execute"


def test_commands_available_and_options_shape() -> None:
    note = commands_available_notification("sid-cmd")
    assert note["method"] == "_kiro.dev/commands/available"
    names = {item["name"] for item in note["params"]["commands"]}
    assert {"compact", "help", "tools", "usage", "clear", "context"} <= names
    update = available_commands_update_message("sid-cmd")
    assert update["params"]["update"]["sessionUpdate"] == "available_commands_update"
    compact = command_options_result({"command": "compact", "partial": ""})
    assert compact["options"]
    assert compact["hasMore"] is False
    help_opts = command_options_result({"command": {"command": "help"}, "partial": "comp"})
    assert any(item["value"] == "compact" for item in help_opts["options"])
