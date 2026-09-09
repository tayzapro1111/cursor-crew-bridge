# Internals

Launchers and Autopilot routes: [AUTOPILOT.md](AUTOPILOT.md). This page is the wire.

Crew never calls Cursor’s HTTP API. It speaks **Agent Client Protocol** (JSON-RPC over stdin/stdout) to whatever binary is in `KIROCREW_KIRO_BIN`.

Official install: that binary is `%LOCALAPPDATA%\Kiro-Cli\kiro-cli.exe` (Kiro credits).

This repo: that binary is `.venv\Scripts\kiro-cli.exe`, an entry point of `cursor-crew-bridge`. Crew still thinks it launched Kiro. The child starts **Cursor Agent CLI** in `acp` mode with your local Cursor session.

```text
┌─────────────┐  ACP / JSON-RPC   ┌──────────────────────┐  ACP   ┌────────────────┐
│  Kiro Crew  │ ────────────────► │ kiro-cli shim        │ ─────► │ Cursor Agent   │
│  dashboard  │ ◄──────────────── │ (this package)       │ ◄───── │  Grok 4.6      │
└─────────────┘  tool chips,      └──────────────────────┘        └────────────────┘
                 session/new,           │
                 session/prompt         │ reads token from
                                        │ Cursor IDE state.vscdb
                                        │ (IDE may be closed)
```

## Why Crew does not need a Kiro subscription

Crew’s `agent.provider` stays `acp`. The only switch is the path of the ACP child. Usage is whatever Cursor Agent bills on your Cursor plan. Unpin with `start-kiro-default.bat` and the official CLI is restored.

## What the shim pretends to be

`cursor_crew_bridge.launcher` answers the same argv Crew already sends:

| Crew calls | Shim does |
|---|---|
| `kiro-cli --version` | Banner `kiro-cli 2.15.0-cursor-crew-bridge` |
| `kiro-cli whoami` | Cursor email from Agent `status` or the IDE cache |
| `kiro-cli agent validate` | Exit 0 |
| `kiro-cli chat --list-models` | Catalog row whose `model_id` equals `model_name` (Crew’s lock icon compares those strings) |
| `kiro-cli acp --agent <name>` | Translate ACP and spawn Cursor Agent |

## ACP translation (the real product)

`acp_bridge.py` sits between Crew’s dialect and Cursor’s:

- Protocol handshake: Crew `2025-08-22` ↔ Cursor protocol `1`. `clientCapabilities` from Crew are forwarded as-is (fs/terminal stay false; elicitation is passed through). The initialize **result** advertises `agentInfo` `{name: kiro-cli, version: 2.15.0}` (Crew's `agent_version_from_init` / MCP hot-reload gate) plus `serverInfo` for the shim version.
- `session/new` is a fresh Cursor session. Initialize copies Cursor’s real `loadSession` and `promptCapabilities` (image/audio/embeddedContext). If Cursor can `session/load`, Crew’s load is **forwarded** with the same MCP roster so Grok keeps the thread. If it cannot (typical until Cursor advertises it), load is **refused** (no kiro `{sid}.json`) and Crew does `session/new` plus `[CONVERSATION HISTORY]`. The shim **replaces that 80k tail** on the first prompt with a compressed whole-slot thread (head included). Raw tools/thoughts are not replayed; condensed tool facts may appear in the summary. A fake successful load used to mark the slot RESUMED and leave Grok empty.
- Crew `session/cancel` is forwarded as an ACP **notification** (no JSON-RPC `id`). The session stays. Terminate (`_kiro.dev/session/terminate`) also notifies cancel, then drops `sessionId`. Older builds sent cancel as a request and wiped the session — Cursor kept talking, Crew showed `[Stopped]`.
- `_kiro.dev/*` (commands/execute, compaction/status, commands/options, …) is local-acked. Cursor has no kiro extensions. After session start the shim emits `_kiro.dev/commands/available` and `available_commands_update` (`compact`, `clear`, `context`, `help`, `tools`, `usage`). `commands/options` returns `{options, hasMore}`. Bare `/help` as `session/prompt` is answered locally (Crew's prompt-transport commands). `/usage` `/tools` `/context` `/clear` go through `commands/execute` and the shim returns `{message}` so Crew's `format_command_result` paints the card. Forwarding those to Grok searches the repo. Compaction/status RPC acks `{status:idle, supported:true}`. `/compact` as a prompt is **not** forwarded into the full child: the shim opens a new Cursor session **off the Crew-handler task** so Cursor stdout stays readable (awaiting `session/new` on that task photofinished at 20s/90s/180s). MCP permissions during rotate are auto-allowed because Crew is blocked on compaction status; quiet only the seed prompt; 180s waiter is a safety net. It seeds the session with an extractive summary of the **whole** Crew `conversation_log` (head included, not the 80k recycle tail), keeps the Crew-facing `sessionId`, emits `{type:completed}` **while the `/compact` prompt is still open**, then a real assistant chunk (`Compacted in place.`), then `end_turn` and a reset `usage_update`. Crew's compaction banner is `kind=compaction` (skipped by `is_turn_interrupted`); status after `end_turn` also `purge_chunks()` the streamed reply and leaves Resume. Crew stays on the same session. `{type:failed}` is only if rotate+seed dies — then autocompact recycles. The bridge never writes or truncates JSONL. Thoughts stay out of the next prompt. Memory / lessons are Crew’s first-prompt prefix. Embeddings and Kiro-Q have no path in the shim.
- `session/set_mode` / `session/set_model` are **not** forwarded (those extra RPCs after `session/new` exited Cursor with rc=1). The ack names the Crew latch / the child that is actually running, and `current_mode_update` updates the mode bar. Unknown modes return `-32602`.
- `session/request_permission` is forwarded to Crew as a permission card except during `/compact` rotate (Crew is blocked on compaction status, so the shim auto-allows). Missing `name`/`label` are copied from each other. Approve/reject echo Cursor’s advertised `optionId`s.
- `available_commands_update` / `current_mode_update` / `session_info_update` are forwarded. Cursor `agent`/`plan`/`ask` is rewritten to the Crew-facing mode id (`kirocrew`, …).
- Model ids: Crew may send `auto` / `claude-opus-5`. The bridge rewrites them to a **suffixed** Cursor id (`cursor-grok-4.6-xhigh`). Bare `cursor-grok-4.6` is rejected by Cursor and is never sent. The set_model **result** still reports the real child id.
- Lite / Optimize Prompt (`kirocrew-lite`) uses `cursor-grok-4.6-high-fast` and `mcp=0` so the wand does not hang.
- If Cursor prints `Cannot use this model`, the shim kills the ACP child and fails open Crew RPCs instead of waiting 90s × 2.
- `cursor/ask_question` is not auto-answered. The shim emits a Crew `AskUserQuestion` tool_call (card via `question_card` WS). Outcome back to Cursor is `skipped`. Fallback: options as chat text only if the payload has no valid questions. `cursor/task` becomes a thought bubble. `cursor/generate_image` is an image block (or a `[generated image](url)` line when Cursor omitted base64). `cursor/create_plan` stays accepted+dropped.
- MCP servers on `session/new` / `session/load` are the `--agent` stand-in Cursor never reads itself: Crew incoming stubs first, then gateway overlay stubs (`~/.kiro/crew/mcp-gateway/agents/`), then `~/.kiro/agents/<agent>.json`. Native `includeMcpJson` is false, so extra `mcp.json` files are not merged. Incoming `kirocrew-core` wins so the gateway identity stays. After a successful new/load the shim emits `_kiro.dev/mcp/server_initialized` for each forwarded server (Cursor does not).
- Context window advertised to Crew is **256k** (including lite `cursor-grok-4.6-high-fast`). The shim also emits `usage_update` (used ≈ prompt chars/4, monotonic). Native kiro-cli streams that; Cursor does not — without it the tooltip stays 0%. Autocompact is 70% of that window (179200), not of a 1M reference cap.
- Autopilot / system prompt: Crew injects memory, skills, `_CRITICAL_RULES`, and `[CURRENT AGENT]` itself. kiro-cli would also load `prompt.md` or `prompt-orchestrator.md` via `--agent`. Cursor never gets `--agent`, so the first prompt of a Cursor session prepends that real file (same `_prompt_path` order), plus `.kiro/steering/**/*.md`, plus a tiny Cursor-RPC delta (`cursor/create_plan` dropped; do not write `stage_N_result.md`). Later turns are not re-injected, except one extra `prompt-orchestrator.md` if the session latches Autopilot after a normal first turn. `cursor/create_plan` stays accepted+dropped (accept would race Crew’s Go). Autopilot UI is still only `📋 Plan for:` + `[OPTION: Go | Go All | Cancel]`. Product tools come from MCP `tools/list`, not a shim encyclopedia. `cursor/task` stays a thought bubble — it is not `spawn_sub_agents`.
- Edit titles: Cursor `Edit \`D:\\abs\\file.ts\`` → `Editing file.ts` with `rawInput.path` using `/` so Crew’s chip does not leave `Edit ""`. Tool identity for Crew is `_meta.kiro.toolName` / `mcpServerName`, not the prose title: Cursor `Read`→`fs_read`, `Shell`→`execute_bash` with `kind=execute`, MCP `mcp__server__tool`→`@server/tool`.
- TRACE (`CURSOR_CREW_TRACE=1`) logs `crew→` methods and short `cursor←` thought/tool chips. Tokens are never logged. `CURSOR_CREW_DUMP=1` (or a path) appends redacted ACP JSONL for native vs shim dumps.

## Profiles

`cursor-crew gateway` (the `.bat`):

1. Stops `KiroCrew.exe` so it re-reads `.env`.
2. Reaps leaked Cursor ACP workers (not Cursor IDE, not Next.js).
3. Writes `KIROCREW_KIRO_BIN` + model env keys.
4. Patches `~/.kiro/crew/config.json`: `eager_spawn`, long Extra High timeouts, `kirocrew-core` stub.
5. Aligns `model_windows.json` keys to 256k.
6. Starts Kiro Crew and waits for `http://127.0.0.1:5476/`.

`cursor-crew default` puts official `kiro-cli` back and removes the Cursor-only env keys.

## Auth

`cursor_auth.py` reads `cursorAuth/accessToken` from the Cursor IDE SQLite DB (`state.vscdb`). The token is passed to the Agent as `--auth-token` and `CURSOR_AUTH_TOKEN`. It is never printed. Override: `CURSOR_AUTH_TOKEN` or `CURSOR_AUTH_DB`.

## Optional Crew patches

`scripts/apply_crew_autopilot_patches.py` patches *installed* Kiro Crew site-packages (stage resume after `✅ Stage N complete`, Optimize Prompt empty-stream recycle). That is optional and machine-local. The ACP shim works without it.
