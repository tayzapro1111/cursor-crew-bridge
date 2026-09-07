# Troubleshooting

Run this first. It never prints secrets.

```powershell
.\.venv\Scripts\python.exe -m cursor_crew_bridge.cli doctor
```

## Cancel / «Отменить» does not stop the model

Crew sends `session/cancel` as a **JSON-RPC notification** (no `id`). The ack is `stopReason: cancelled` on the in-flight `session/prompt`.

Bridge **0.4.0** forwards that notification as-is and **keeps** `sessionId`. Older builds sent cancel as a request (`id: …`) and then cleared the session. Cursor kept generating; Crew painted `[Stopped]` on every tool chip. That is a **bridge bug**, not “you must reboot the gateway.”

- This live ACP child was spawned before 0.4.0 → Cancel still looks dead until the **next** `session/new` (new chat / idle recycle).
- After a 0.4.0 child: `bridge.log` shows `session/cancel notification sid=…` with no `id=` on the Cursor frame. Streaming tool/text frames are dropped until the prompt result.

Do not restart the whole Kiro Crew gateway just to test Cancel. Open a new chat slot after the shim is updated (`pip install -e .` already live for *new* children).

## Context window stays 0%

Native kiro-cli streams `usage_update` / `contextUsagePercentage`. Cursor Agent does not. Bridge 0.3.1 synthesizes both from prompt size (chars/4).

- The **current** dashboard slot keeps the old ACP child until Crew recycles it. Open a new chat, or wait for idle recycle — do not restart the whole gateway unless you want that.
- After the next `session/prompt` on a 0.3.1 child, `bridge.log` should show `usage used=… window=256000`.

## Optimize Prompt does nothing

The wand POSTs `/api/optimizer/optimize` to a dedicated `_optimizer` slot (`kirocrew-lite`).

- Cursor must receive a **suffixed** model id. Bare `cursor-grok-4.6` dies in ~3s (`Cannot use this model`). The shim maps lite to `cursor-grok-4.6-high-fast`.
- If `doctor` is green and the wand still returns `{changed:false}`, look at `bridge.log` for `spawn agent=kirocrew-lite`. A new spawn per click is normal.
- A **gateway process restart** is only needed to load *Crew* `optimizer.py` site-packages patches. The model / fail-fast / TRACE path lives in each new `kiro-cli` child (editable install).

## Crew still uses Kiro credits

`KIROCREW_KIRO_BIN` is not the shim, or Crew was not restarted after `setup`.

1. `cursor-crew status` — `shim` must exist.
2. `start-cursor-gateway.bat` (it stops Crew so `.env` is re-read).
3. Confirm `~/.kiro/crew/.env` contains `KIROCREW_KIRO_BIN=...\cursor-crew-bridge\.venv\Scripts\kiro-cli.exe`.

## `Cannot use this model`

The id sent to Cursor was not in the catalog. Check `CURSOR_CREW_MODEL` / `CURSOR_CREW_LITE_MODEL`. Allowed values are listed in [CONFIGURATION.md](CONFIGURATION.md).

## No Cursor token

Open Cursor, sign in, close it. `doctor` should show `cursor_login` OK. Corporate machines that wipe `%APPDATA%\Cursor` will need a new login. You can set `CURSOR_AUTH_TOKEN` instead (do not commit it).

## Cursor Agent CLI not found

The bridge never uses `%USERPROFILE%\.grok\bin\agent.exe` (xAI). Install Cursor’s CLI:

```powershell
irm "https://cursor.com/install?win32=true" | iex
```

Or set `CURSOR_AGENT_BIN`.

## Dashboard does not open

Gateway already started `KiroCrew.exe`. Wait and open `http://127.0.0.1:5476/`. If the exe path is custom, set `KIROCREW_EXE`.

## Chat is a flood of Read / Edit chips

Those are native Crew tool pills, not errors. Extra High emits more `tool_call`s than a small Claude turn. Hiding them would *not* be 1:1 with native Crew.

## Hung ACP / leftover node processes

`start-cursor-gateway.bat` reaps leaked Cursor ACP workers. It will not kill Cursor IDE or a Next.js `node`.

## Logs to attach to an issue

- `bridge.log` in the repo (redact anything that looks like a token; the shim already redacts `--auth-token`).
- `doctor` output.
- Crew version and Windows build. **Never** attach `state.vscdb`.
