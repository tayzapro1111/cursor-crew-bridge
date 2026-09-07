import re

from cursor_crew_bridge.native_parity import (
    ADVERTISE_LOAD_SESSION,
    PLAN_FOOTER,
    PLAN_HEADER,
    PLANNING_STEER,
    PLAN_TEMPLATE,
    STAGE_STEER,
    UsageTracker,
    cursor_prompt_used_tokens,
    cursor_todos_crew_messages,
    cursor_todos_snapshot,
    drop_update_after_cancel,
    enrich_cursor_tool_update,
    estimate_tokens,
    is_stage_execution,
    looks_like_orchestrator,
    normalize_fs_path,
    prepend_prompt_blocks,
    prompt_cancelled_result,
    remember_orchestrator,
    session_cancel_notification,
    session_load_error,
    steering_texts,
    usage_update_message,
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


def test_usage_update_shape_matches_crew_parse() -> None:
    msg = usage_update_message("sid-1", 180_000, 256_000)
    update = msg["params"]["update"]
    assert msg["method"] == "session/update"
    assert update["sessionUpdate"] == "usage_update"
    assert update["used"] == 180_000
    assert update["size"] == 256_000


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
    assert any("AUTOPILOT — native" in item for item in first)
    assert any("BROWSER" in item for item in first)
    already.update({"plan", "browser"})
    stage_params = {"prompt": [{"type": "text", "text": "Execute Stage 1 of 3 now."}]}
    second = steering_texts(stage_params, agent="kirocrew", crew_mode="orchestrator", already=already)
    assert any("stage execution" in item for item in second)
    assert not any("BROWSER" in item for item in second)
    already.add("stage")
    third = steering_texts(stage_params, agent="kirocrew", crew_mode="orchestrator", already=already)
    assert any("stage execution" in item for item in third)


def test_midchat_latch_keeps_planning_steer() -> None:
    assert remember_orchestrator("Execute Stage 1 of 3 now.", "kirocrew") == "orchestrator"
    assert remember_orchestrator("plain bugfix", "kirocrew") == "kirocrew"
    assert remember_orchestrator("plain bugfix", "orchestrator") == "orchestrator"
    already = {"plan", "browser"}
    later = {"prompt": [{"type": "text", "text": "now fix the remaining callers"}]}
    extras = steering_texts(later, agent="kirocrew", crew_mode="orchestrator", already=already)
    assert any("AUTOPILOT — native" in item for item in extras)
    assert not any("BROWSER" in item for item in extras)
    plain = steering_texts(later, agent="kirocrew", crew_mode="kirocrew", already=already)
    assert not any("AUTOPILOT — native" in item for item in plain)


def test_planning_steer_matches_orchestrator_contract() -> None:
    assert PLAN_HEADER in PLANNING_STEER
    assert PLAN_FOOTER in PLANNING_STEER
    assert "cursor/create_plan" in PLANNING_STEER
    assert "cursor/update_todos" in PLANNING_STEER
    assert "Verification" in PLANNING_STEER
    assert "STOP" in PLANNING_STEER
    assert "rubber" in STAGE_STEER
    assert PLAN_FOOTER in STAGE_STEER


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
