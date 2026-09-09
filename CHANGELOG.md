# Changelog

## Unreleased

## 0.8.0

- **Local slash commands:** Crew sends `/help` as `session/prompt` and `/usage` `/tools` `/context` `/clear` as `_kiro.dev/commands/execute`. The shim answers both locally (`result.message` for execute, so Crew's `format_command_result` paints the card). Bare `/help` no longer burns a Grok turn searching the repo.
- **Compact rotate:** `/compact` must not await Cursor on the same task that reads Cursor stdout (that photofinished at 20s/90s/180s). `run()` detaches compact, auto-allows MCP permissions while Crew is blocked on compaction status, quiets only the seed prompt, cancels the previous Cursor session **without** rewriting that cancel onto the new sid, and drops frames from the retired sid. Waiter is 180s plus a 15s late-result grace. Untracked late `sessionId` results are not forwarded to Crew. After rotate the shim emits `_kiro.dev/compaction/status` `completed` **while the `/compact` prompt is still open**, then an assistant `agent_message_chunk`, then `end_turn`. Status after `end_turn` makes Crew `purge_chunks()` and treat the banner as a system notice, which leaves Resume on the composer. Cursor `session/update` frames during rotate are not forwarded, and Crew `session/cancel` during compact is ignored.
- **Crew-facing kiro-cli wire:** `initialize` now sends `agentInfo` `{name: kiro-cli, version: 2.15.0}` (Crew reads this, not `serverInfo`). After `session/new` / `session/load` the shim emits `_kiro.dev/commands/available` plus `available_commands_update`. `_kiro.dev/commands/options` returns `{options, hasMore}` instead of `{}`.
- **Tool identity:** outbound `tool_call` / permission `toolCall` frames get `_meta.kiro.toolName` (and `mcpServerName` for MCP). Cursor `kind=shell` becomes kiro `kind=execute` (`execute_bash`). Permission options expose both `optionId` and `id`.
- **Late Autopilot:** if a session starts as a normal chat and later latches orchestrator, the next prompt gets `prompt-orchestrator.md` once. Official kiro-cli sources are proprietary; analogs live in gitignored `acp-analogs/`.

## 0.7.0

- **KISS 1:1 `--agent` stand-in:** MCP roster is Crew stubs + gateway overlay + agent spec only (`includeMcpJson` is false — extra `mcp.json` files are not merged). After `session/new` / `session/load` the shim synthesizes `_kiro.dev/mcp/server_initialized` so Crew UI banners match kiro-cli. First Cursor prompt gets the real `prompt.md` or `prompt-orchestrator.md` plus steering resources and a tiny Cursor-RPC delta, once per session. Host-identity / browser / Autopilot paraphrases are gone. Optional `CURSOR_CREW_DUMP` writes redacted ACP JSONL.

## 0.6.0

- **1:1 Kiro Crew host:** Cursor ACP does not read `--agent`. `session/new` / `session/load` now send Crew stubs + gateway overlay + agent spec + extra `mcp.json` names (incoming `kirocrew-core` still wins). First turn injects host identity and `.kiro/steering/**/*.md`. Autopilot prepends the real `prompt-orchestrator.md` (not a Fable paraphrase) plus the Crew-parser / Cursor-RPC delta.
- **session/load:** advertise Cursor’s real `loadSession` / `promptCapabilities`. When Cursor can load, the RPC is forwarded so Grok keeps the thread; on failure Crew still gets `-32001` and replays. Fake-success load is gone.
- `initialize` forwards Crew `clientCapabilities` including elicitation.

- **In-place compact (0.5.0):** `/compact` rotates the Cursor session and seeds the **full** Crew `conversation_log` (head included, ~120k chars / ~12% of 256k). Crew gets `_kiro.dev/compaction/status` `{type:completed}` so it does **not** recycle to the 80k tail (~8%). Crew JSONL is never rewritten. If `session/new` fails, the shim still emits `{type:failed}` and Crew recycles. A slow `COMPACT_OK` after a successful rotate is not a failure.
- **Cursor extras:** `cursor/ask_question` becomes a Crew `AskUserQuestion` card (`rawInput.questions`, title exact — `select_tool_title` must not steal it). Outcome is `skipped`, never the first option. `cursor/task` is an `agent_thought_chunk`. `cursor/generate_image` forwards a base64 image block, or a markdown link when Cursor only sent a url/path. `cursor/create_plan` stays accepted+dropped (`wont`). Permission options fill both `name` and `label`. `session/new` MCP merge: incoming Crew stub wins; lite/`skip_mcp` stay empty.
- **Replay after death:** the first `session/prompt` after `session/new` replaces Crew’s `[CONVERSATION HISTORY]` 80k tail with a compressed whole-slot thread (head included). Raw `tool`/`thought` rows stay out of the prompt; unique tool first-lines are facts in the summary. Later prompts are untouched.
- **Persist / compact:** `/compact` is not forwarded into the full Cursor child. The shim rotates a new Cursor `session/new`, seeds it from the **whole** Crew `conversation_log` (not the 80k recycle tail), keeps the Crew `sessionId`, emits `_kiro.dev/compaction/status` `{type:completed}` plus a low `usage_update`, then `end_turn`. Crew does not recycle. JSONL is read-only. `{type:failed}` is last-resort when rotate+seed cannot run. `compaction/status` RPC acks `{status:idle, supported:true}`. `session/load` is forwarded when Cursor advertises it, otherwise `-32001`.
- **Memory contract:** Crew first-prompt prefix only. Embeddings / Kiro-Q stay out of the bridge. Thoughts are never prepended. Replay roles stay Crew `user` / `assistant` / `inject`.
- Lite / high-fast window keys stay 256k (same Extra High cap).
- **Session-core parity:** `session/set_mode` / `session/set_model` stay local (forwarding those RPCs after `session/new` still kills Cursor ACP), but the ack is honest: `result.modes.currentModeId` is the Crew latch, `result.models.currentModelId` is the child that is actually running. Unknown modes fail `-32602`. A `current_mode_update` is emitted after `session/new` and `set_mode`.
- **Permission card:** `session/request_permission` is forwarded to Crew (no auto-allow). Option ids are rewritten/mapped so approve/reject echo Cursor’s advertised ids.
- **Plumbing updates:** `available_commands_update` / `current_mode_update` / `session_info_update` are no longer dropped. Cursor `agent`/`plan`/`ask` is rewritten to the Crew-facing mode id.
- Lite `session/new` advertises `currentModelId=cursor-grok-4.6-high-fast`.

## 0.4.0

- Docs split: landing pages per language, [Autopilot two backends](docs/AUTOPILOT.md), GitHub Release + wheel on tag `v0.4.0`.
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
