# Changelog

## 0.4.0

- **Cancel:** Crew `session/cancel` is an ACP notification. The shim no longer sends it as a request or clears `sessionId`. After cancel, in-flight tool/text frames are dropped; if Cursor never acks, a 6s watchdog synthesizes `stopReason: cancelled`. That was why «Отменить» painted `[Stopped]` while the model kept talking.
- **Windows paths:** `rawInput.path` is normalized to `/` so Crew’s `split('/')` chip shows the basename.
- **Todos:** `cursor/update_todos` becomes a kiro `todo_list` `_meta` + `rawOutput` snapshot for the Crew sidebar. `cursor/create_plan` is still dropped.
- **Tokens:** if Cursor returns `usage.totalTokens` / `promptTokens`, the meter prefers that over chars/4.
- **macOS / Linux:** `setup.sh`, `start-cursor-gateway.sh`, `start-kiro-default.sh`; `KIROCREW_EXE` / official `kiro-cli` discovery; `cursor-crew gateway` writes `.env` even when it cannot launch the app.
- Docs: install for three OSes, i18n READMEs, CI on Ubuntu/Windows/macOS.

## 0.3.1

- Tool pills: rewrite Cursor `Edit File` / `Edit \`D:\\abs\\file.ts\`` to native `Editing file.ts` and put `path` on `rawInput` so Crew's chip does not leave `Edit ""`. Distinct `toolCallId`s stay one row each.
- Autopilot: latch orchestrator from `_stage_loop` / plan chrome (Crew `set_mode` is `kirocrew`, not `orchestrator`). Re-send Fable plan/stage steers every matching turn. `cursor/create_plan` stays accepted+dropped — Crew parses only the text footer.
- Context meter: synthesize `usage_update` `{used, size}` and `_kiro.dev/metadata.contextUsagePercentage`. Cursor never sent them, so Crew showed 0% / 256K.
- Autopilot: prepend Fable plan/stage/browser contracts on `session/prompt` (Crew injects `prompt-orchestrator.md` only on the first turn of a new orchestrator session).
- History: `session/load` now errors like a missing kiro `{sid}.json`. Initialize advertises `loadSession: false`. A fake successful load marked the slot RESUMED and skipped `conversation_log` replay.
- Browser steer: MCP `browser` first; no `playwright-cli` while the Crew panel exists.

## 0.3.0

- Relocatable checkout: `discover_project_dir()` (no hardcoded `D:\` required for clones).
- `setup.bat` / `setup.ps1` and `cursor-crew setup|doctor|help`.
- Docs for GitHub: how the ACP layer works, install, config, troubleshooting.
- MIT license, issue/PR templates, CI.

ACP translation, model pins, and gateway/default profiles are unchanged.

## 0.2.4

- Lite model is always a suffixed Cursor id (`cursor-grok-4.6-high-fast`).
- Fail-fast when Cursor rejects the model.
- ACP TRACE journal.
