"""Re-apply Crew 1:1 autopilot + Optimize Prompt patches after a KiroCrew update."""

from __future__ import annotations

import sys
from pathlib import Path

CREW = (
    Path.home()
    / "AppData"
    / "Local"
    / "Programs"
    / "KiroCrew"
    / "resources"
    / "backend-dist"
    / "kirocrew-backend"
    / "Lib"
    / "site-packages"
    / "kiro_crew"
    / "dashboard"
)

ORCH = CREW / "chat_orchestrator.py"
HANDLERS = CREW / "chat_handlers.py"
OPTIMIZER = CREW / "handlers" / "optimizer.py"

RESUME_FN = '''
_STAGE_COMPLETE_RE = re.compile(r"(?i)(?:✅\\s*)?\\*{0,2}Stage\\s+(\\d+)\\s+complete")


def last_completed_stage(slot: "_ChatSlot") -> int | None:
    for msg in reversed(getattr(slot, "messages", []) or []):
        if msg.get("role") != "assistant":
            continue
        match = _STAGE_COMPLETE_RE.search(str(msg.get("content") or ""))
        if match:
            return int(match.group(1))
    return None


async def maybe_resume_autorun_from_turn(state: "DashboardState", slot: "_ChatSlot") -> None:
    """If a regular turn just wrote Stage N complete, inject Stage N+1 like Go All."""
    if getattr(slot, "mode", "") != "orchestrator":
        return
    if getattr(slot, "_in_stage_execution", False) or getattr(slot, "_plan_cancelled", False):
        return
    if getattr(slot, "_stopping", False) or getattr(slot, "running", False):
        return
    total = int(getattr(slot, "_plan_stage_count", 0) or 0)
    if total <= 0:
        return
    tracker = slot._orch_tracker
    if tracker is None or tracker.stopped:
        return
    completed = last_completed_stage(slot)
    if not completed:
        return
    recorded = max(tracker._stage_results.keys(), default=0)
    if completed > recorded:
        try:
            path = _capture_stage_result(slot, completed)
            tracker.record_stage_result(completed, path)
        except OSError:
            logger.warning("Failed to capture late stage %s result", completed, exc_info=True)
        recorded = max(tracker._stage_results.keys(), default=recorded)
    if recorded >= total:
        return
    slot._auto_run = True
    logger.info(
        "Resuming auto-run for slot %s after Stage %s complete → Stage %s",
        slot.key,
        completed,
        recorded + 1,
    )
    task = asyncio.create_task(_stage_loop(state, slot, auto_run=True))
    slot.task = task
    state._background_tasks.add(task)
    task.add_done_callback(state._background_tasks.discard)
    state.push_slots_update()

'''

RESUME_HOOK = '''
    def _resume_autorun(done: asyncio.Task) -> None:
        if done.cancelled():
            return
        try:
            if done.exception() is not None:
                return
        except (asyncio.CancelledError, asyncio.InvalidStateError):
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        nxt = loop.create_task(maybe_resume_autorun_from_turn(state, slot))
        state._background_tasks.add(nxt)
        nxt.add_done_callback(state._background_tasks.discard)

    task.add_done_callback(_resume_autorun)
'''


def _replace_once(text: str, old: str, new: str) -> tuple[str, bool]:
    if new in text:
        return text, True
    if old not in text:
        return text, False
    return text.replace(old, new, 1), True


def _patch_orchestrator(text: str) -> str:
    for old in (
        "    start_idx = tracker.current_stage\n",
        "    start_idx = max(0, int(tracker.current_stage or 0))\n",
        "    start_idx = max(0, tracker.current_stage)\n",
    ):
        text, _ = _replace_once(
            text,
            old,
            "    start_idx = max(tracker._stage_results.keys(), default=0)\n",
        )
    if "async def maybe_resume_autorun_from_turn" not in text:
        needle = "async def api_chat_plan_action"
        if needle in text:
            text = text.replace(needle, RESUME_FN + needle, 1)
    if "import re\n" not in text:
        text = text.replace("import logging\n", "import logging\nimport re\n", 1)
    return text


def _patch_handlers(text: str) -> str:
    text, _ = _replace_once(
        text,
        "from kiro_crew.dashboard.chat_orchestrator import _stage_loop\n",
        "from kiro_crew.dashboard.chat_orchestrator import _stage_loop, maybe_resume_autorun_from_turn\n",
    )
    text, _ = _replace_once(
        text,
        '    _orch_go_all = _orch_cmd == "go all"\n',
        '    _orch_go_all = _orch_cmd == "go all" or (\n'
        "        _has_plan\n"
        "        and _orch_cmd in {\n"
        '            "continue",\n'
        '            "продолжай",\n'
        '            "продолжи",\n'
        '            "продолжить",\n'
        "        }\n"
        "    )\n",
    )
    if "_has_plan = int(getattr(slot, \"_plan_stage_count\", 0) or 0) > 0" not in text:
        text, _ = _replace_once(
            text,
            "    _orch_cmd = message.strip().lower()\n",
            "    _orch_cmd = message.strip().lower()\n"
            '    _has_plan = int(getattr(slot, "_plan_stage_count", 0) or 0) > 0\n',
        )
    if "maybe_resume_autorun_from_turn(state, slot)" not in text:
        text, _ = _replace_once(
            text,
            "    slot.task = task\n    slot._recovery_retrigger_count = 0\n",
            "    slot.task = task\n    slot._recovery_retrigger_count = 0\n" + RESUME_HOOK,
        )
    return text


def _patch_optimizer(text: str) -> str:
    text, _ = _replace_once(
        text,
        "            text = await asyncio.wait_for(_optimize(), timeout=30.0)\n",
        "        try:\n"
        "            text = await asyncio.wait_for(_optimize(), timeout=90.0)\n"
        "        except asyncio.TimeoutError:\n"
        '            logger.warning("Optimizer timed out (90s) — retrying once on warm session")\n'
        "            text = await asyncio.wait_for(_optimize(), timeout=90.0)\n",
    )
    text, ok = _replace_once(text, "timeout=30.0", "timeout=90.0")
    if ok and "retrying once on warm session" not in text:
        text, _ = _replace_once(
            text,
            "            text = await asyncio.wait_for(_optimize(), timeout=90.0)\n"
            "        finally:\n",
            "        try:\n"
            "            text = await asyncio.wait_for(_optimize(), timeout=90.0)\n"
            "        except asyncio.TimeoutError:\n"
            '            logger.warning("Optimizer timed out (90s) — retrying once on warm session")\n'
            "            text = await asyncio.wait_for(_optimize(), timeout=90.0)\n"
            "        finally:\n",
        )
    if "logger.setLevel(logging.INFO)" not in text:
        text, _ = _replace_once(
            text,
            "logger = logging.getLogger(__name__)\n",
            "logger = logging.getLogger(__name__)\n"
            "logger.setLevel(logging.INFO)\n",
        )
    return text


def apply() -> list[str]:
    missing: list[str] = []
    jobs = (
        (ORCH, _patch_orchestrator, "max(tracker._stage_results.keys(), default=0)"),
        (ORCH, _patch_orchestrator, "maybe_resume_autorun_from_turn"),
        (HANDLERS, _patch_handlers, "продолжай"),
        (OPTIMIZER, _patch_optimizer, "timeout=90.0"),
        (OPTIMIZER, _patch_optimizer, "logger.setLevel(logging.INFO)"),
    )
    seen: set[str] = set()
    for path, patcher, needle in jobs:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        if not path.is_file():
            missing.append(key)
            continue
        original = path.read_text(encoding="utf-8")
        updated = patcher(original)
        if updated != original:
            path.write_text(updated, encoding="utf-8")
    for path, _patcher, needle in jobs:
        if not path.is_file() or needle not in path.read_text(encoding="utf-8"):
            missing.append(f"{path} :: {needle}")
    return missing


def main() -> int:
    missing = apply()
    if missing:
        print("Crew patches missing or overwritten:")
        for item in missing:
            print("  " + item)
        return 1
    print("Crew autopilot + optimizer patches are present.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
