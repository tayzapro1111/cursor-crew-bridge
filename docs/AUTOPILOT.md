# Autopilot — two backends, one Crew UI

Kiro Crew Autopilot is the cards: `📋 Plan for:` and `[OPTION: Go | Go All | Cancel]`. The child behind `KIROCREW_KIRO_BIN` changes how those cards get a model that obeys them.

## Path A — Cursor (`start-cursor-gateway`)

Crew still sends `session/set_mode` with the **agent name** (`kirocrew`), not `orchestrator`. Official `kiro-cli` would have loaded `prompt-orchestrator.md` on a brand-new orchestrator session. Cursor never sees that file.

This package therefore:

1. Latches Autopilot when the prompt looks like a plan or a `_stage_loop` inject.
2. Prepends a plan contract (`PLANNING_STEER`) or a stage contract (`STAGE_STEER`) on **every** matching turn, not only the first.
3. Accepts and **drops** Cursor’s `cursor/create_plan` (accepting it races Crew’s Go button).
4. Maps `cursor/update_todos` into Crew’s todo sidebar.

You stay in the Crew Autopilot UI. Do not expect Cursor IDE’s own plan panel.

## Path B — official Kiro (`start-kiro-default`)

`KIROCREW_KIRO_BIN` points at `%LOCALAPPDATA%\Kiro-Cli\kiro-cli.exe` (or the macOS/Linux install). The shim is not in the path.

Autopilot is whatever current Kiro Crew + `kiro-cli` already do: `prompt-orchestrator.md` on a new orchestrator session, native usage, native `session/load` if a `{sid}.json` exists. You need a Kiro subscription. This repo’s plan/stage steers are **not** injected.

## Switching

```text
start-cursor-gateway.bat    # Path A
start-kiro-default.bat      # Path B
```

Each launcher stops Crew so `.env` is re-read. Open a **new** chat after a switch: the old ACP child still belongs to the previous binary.

## What Crew keeps on both paths

Conversation log, Autopilot cards, MCP roster, memory, Knowledge. Only the ACP child and the invoice change.

## Optional Crew patches

`scripts/apply_crew_autopilot_patches.py` edits *installed* Crew site-packages (resume after `✅ Stage N complete`, Optimize Prompt recycle). Machine-local. Path A works without it.
