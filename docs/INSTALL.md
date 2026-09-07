# Install

You do not replace `kiro-cli.exe` under Program Files. Crew’s official override is `KIROCREW_KIRO_BIN`. Windows, macOS, and Linux all use the same Python package.

## Prerequisites

1. **Python 3.11+** on PATH (`python --version`). Tick “Add python.exe to PATH” on the official installer.
2. **Kiro Crew** desktop app. Default path: `%LOCALAPPDATA%\Programs\KiroCrew\KiroCrew.exe`. Override: `KIROCREW_EXE`.
3. **Cursor IDE** signed in once on this PC. You can quit Cursor after login.
4. **Cursor Agent CLI** — `setup.ps1` installs it from `https://cursor.com/install?win32=true` if missing. `setup.bat` only reports the hint.

## Happy path

```text
git clone https://github.com/Chumbayoumba/cursor-crew-bridge.git
cd cursor-crew-bridge
setup.bat
start-cursor-gateway.bat
```

`setup.bat` is silent about Cursor CLI install. If `doctor` says `cursor_agent` is missing, run `setup.ps1` in PowerShell or:

```powershell
irm "https://cursor.com/install?win32=true" | iex
```

## What setup writes

- `.venv\` with an editable install. Console scripts: `kiro-cli`, `cursor-crew-bridge`, `cursor-crew`.
- `%USERPROFILE%\.kiro\crew\.env` keys `KIROCREW_KIRO_BIN`, `CURSOR_CREW_MODEL`, `CURSOR_CREW_LITE_MODEL`, `CURSOR_CREW_TRACE`, `CURSOR_CREW_SKIP_MCP`, `CURSOR_CREW_BRIDGE_LOG`.

`start-cursor-gateway.bat` then patches Crew `config.json` / `model_windows.json` and launches the app.

## Check

```powershell
.\.venv\Scripts\python.exe -m cursor_crew_bridge.cli doctor
```

Every `[OK]` line must be green for required checks. The report never prints the token.

## Unpin

```text
start-kiro-default.bat
```

or delete `KIROCREW_KIRO_BIN` from `~/.kiro/crew/.env` and restart Crew.

## macOS / Linux

```bash
chmod +x setup.sh start-cursor-gateway.sh start-kiro-default.sh
./setup.sh
./start-cursor-gateway.sh
```

`setup.sh` creates `.venv`, installs the shim, writes `~/.kiro/crew/.env` (`KIROCREW_KIRO_BIN=.venv/bin/kiro-cli`), and tries to install Cursor Agent CLI via `curl https://cursor.com/install -fsSL | bash`.

If `doctor` cannot see Kiro Crew:

```bash
export KIROCREW_EXE=/Applications/KiroCrew.app/Contents/MacOS/KiroCrew   # macOS
# export KIROCREW_EXE=/path/to/KiroCrew                                 # Linux
```

Then `cursor-crew gateway` still writes `.env`. If it cannot launch the app, start Kiro Crew yourself.

## Optional autopilot patches

Only if you want Crew site-packages changes (stage resume, optimizer recycle):

```powershell
.\.venv\Scripts\python.exe scripts\apply_crew_autopilot_patches.py
```

Read the script before you run it. It edits files inside the Crew install.
