# How the bridge works

Kiro Crew does not call Cursor’s HTTP API. It speaks **Agent Client Protocol** (JSON-RPC over stdin/stdout) to whatever binary is in `KIROCREW_KIRO_BIN`.

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

- Protocol handshake: Crew `2025-08-22` ↔ Cursor protocol `1`.
- `session/new` is a fresh Cursor session. Initialize advertises `loadSession: false`. If Crew still sends `session/load`, it is **refused** (no kiro `{sid}.json`). Crew then does `session/new` and replays `conversation_log`. A fake successful load used to mark the slot RESUMED and leave Grok empty.
- Crew `session/cancel` is forwarded as an ACP **notification** (no JSON-RPC `id`). The session stays. Terminate (`_kiro.dev/session/terminate`) also notifies cancel, then drops `sessionId`. Older builds sent cancel as a request and wiped the session — Cursor kept talking, Crew showed `[Stopped]`.
- `_kiro.dev/*` (commands/execute, compaction/status, …) is local-acked. Cursor has no kiro extensions.
- Model ids: Crew may send `auto` / `claude-opus-5`. The bridge rewrites them to a **suffixed** Cursor id (`cursor-grok-4.6-xhigh`). Bare `cursor-grok-4.6` is rejected by Cursor and is never sent.
- Lite / Optimize Prompt (`kirocrew-lite`) uses `cursor-grok-4.6-high-fast` and `mcp=0` so the wand does not hang.
- If Cursor prints `Cannot use this model`, the shim kills the ACP child and fails open Crew RPCs instead of waiting 90s × 2.
- `cursor/ask_question` is not auto-answered. Crew sees the options; the first choice is not picked for you.
- MCP servers come from `~/.kiro/agents/kirocrew.json` on `session/new`. Incoming `kirocrew-core` (Crew stub) wins over a raw copy of the same name.
- Context window advertised to Crew is **256k**. The shim also emits `usage_update` (used ≈ prompt chars/4, monotonic). Native kiro-cli streams that; Cursor does not — without it the tooltip stays 0%.
- Autopilot: Crew injects `prompt-orchestrator.md` only on a **new** session, and `session/set_mode` sends the agent name (`kirocrew`), not `orchestrator`. The shim latches Autopilot when a prompt looks like a plan / `_stage_loop` inject, then prepends the Fable plan/stage contract on **every** matching turn. `cursor/create_plan` stays accepted+dropped (accept would race Crew’s Go). `cursor/update_todos` is mapped to a kiro `todo_list` snapshot so the Crew sidebar updates. Autopilot UI is still only `📋 Plan for:` + `[OPTION: Go | Go All | Cancel]`.
- Edit titles: Cursor `Edit \`D:\\abs\\file.ts\`` → `Editing file.ts` with `rawInput.path` using `/` so Crew’s chip does not leave `Edit ""`.
- Browser: the same prepend tells Grok to use MCP `browser`, not `playwright-cli`.
- TRACE (`CURSOR_CREW_TRACE=1`) logs `crew→` methods and short `cursor←` thought/tool chips. Tokens are never logged.

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
