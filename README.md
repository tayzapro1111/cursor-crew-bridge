# cursor-crew-bridge

**Use [Kiro Crew](https://github.com/kirodotdev/KiroCrew) with [Cursor Agent](https://cursor.com) models. No Kiro subscription. No Kiro tokens. Same dashboard.**

`cursor-crew-bridge` is an **ACP (Agent Client Protocol) shim**. Kiro Crew always talks ACP to a `kiro-cli` child. This repo *is* that child: Crew stays the familiar desktop app, the model and the bill come from your Cursor plan (Grok 4.6 Extra High by default).

[Русский](README.ru.md) · [简体中文](docs/i18n/README.zh-CN.md) · [日本語](docs/i18n/README.ja.md) · [Español](docs/i18n/README.es.md) · [Deutsch](docs/i18n/README.de.md) · [Português](docs/i18n/README.pt-BR.md) · [Français](docs/i18n/README.fr.md) · [한국어](docs/i18n/README.ko.md)

[How it works](docs/HOW-IT-WORKS.md) · [Install](docs/INSTALL.md) · [Config](docs/CONFIGURATION.md) · [Troubleshooting](docs/TROUBLESHOOTING.md) · [Changelog](CHANGELOG.md)

![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-3776AB)
![License MIT](https://img.shields.io/badge/license-MIT-green)
![ACP](https://img.shields.io/badge/protocol-ACP-111)
![Platforms](https://img.shields.io/badge/os-Windows%20%7C%20macOS%20%7C%20Linux-informational)
![CI](https://img.shields.io/github/actions/workflow/status/Chumbayoumba/cursor-crew-bridge/ci.yml?label=CI)

> Not affiliated with Kiro / AWS or Anysphere / Cursor. You need a Cursor account (IDE login on this machine) and the Kiro Crew app. You do **not** need a Kiro CLI subscription.

## Why this exists

| You have | What you do |
|---|---|
| Kiro Crew + Cursor login | Run this bridge. Chat in Crew. Tokens go to Cursor. |
| Kiro Crew + Kiro subscription | `start-kiro-default` any time. The bridge steps aside. |
| Neither | Install Crew + sign into Cursor once. That is the whole account setup. |

Kiro Crew is an excellent control plane (slots, Autopilot, MCP, dashboard). Official `kiro-cli` bills Kiro. This package keeps Crew and swaps only the ACP backend to **Cursor Agent CLI**.

## 60-second install

### Windows

1. Install [Kiro Crew](https://github.com/kirodotdev/KiroCrew).
2. Open **Cursor**, sign in, then you can close it. The token stays in the local IDE database.
3. Clone this repository.
4. Double-click **`setup.bat`** (or `setup.ps1` if Cursor Agent CLI is missing).
5. Double-click **`start-cursor-gateway.bat`**.
6. Talk in Kiro Crew. The live model is Cursor Grok 4.6 Extra High.

### macOS

```bash
git clone https://github.com/Chumbayoumba/cursor-crew-bridge.git
cd cursor-crew-bridge
chmod +x setup.sh start-cursor-gateway.sh start-kiro-default.sh
./setup.sh
./start-cursor-gateway.sh
```

Install Kiro Crew (`.app`). Sign into Cursor once. If `doctor` cannot find the app, set `KIROCREW_EXE` to:

`/Applications/KiroCrew.app/Contents/MacOS/KiroCrew`

### Linux

```bash
git clone https://github.com/Chumbayoumba/cursor-crew-bridge.git
cd cursor-crew-bridge
chmod +x setup.sh start-cursor-gateway.sh start-kiro-default.sh
./setup.sh
export KIROCREW_EXE=/path/to/KiroCrew
./start-cursor-gateway.sh
```

Cursor Agent CLI: `curl https://cursor.com/install -fsSL | bash`

## What you get

```text
Kiro Crew  --ACP-->  kiro-cli shim (this repo)  --ACP-->  Cursor Agent
                         ^
                         KIROCREW_KIRO_BIN in ~/.kiro/crew/.env
```

- Native Crew pills: `Editing file.ts` instead of `Edit ""`
- **Cancel** (`Отменить`) stops the Cursor turn — ACP `session/cancel` is a notification, the session stays alive
- Autopilot text plans (`📋 Plan for:` + `[OPTION: Go | Go All | Cancel]`)
- Context meter (`usage_update` 256k) so autocompact is not blind
- Cursor todos appear in Crew’s task sidebar
- Unpin to official Kiro in one command

## Commands

| Do this | Windows | macOS / Linux |
|---|---|---|
| First install | `setup.bat` | `./setup.sh` |
| Daily start (Cursor models) | `start-cursor-gateway.bat` | `./start-cursor-gateway.sh` |
| Back to official Kiro | `start-kiro-default.bat` | `./start-kiro-default.sh` |
| What is broken? | `.venv\Scripts\cursor-crew.exe doctor` | `.venv/bin/cursor-crew doctor` |

```text
cursor-crew setup      # venv + .env
cursor-crew doctor     # checks, no secrets printed
cursor-crew gateway    # point Crew at Cursor and launch
cursor-crew default    # point Crew at official kiro-cli
cursor-crew status
```

## Requirements

- Windows 10/11, macOS, or Linux
- Python 3.11+
- [Kiro Crew](https://github.com/kirodotdev/KiroCrew) desktop app
- Cursor IDE logged in once on this machine
- Cursor Agent CLI (`setup.ps1` / `setup.sh` can install it)

## What this is not

- Not a Kiro Integrations API key
- Not a scrape of the Cursor desktop chat
- Not xAI’s `~/.grok/bin/agent.exe` (the bridge refuses that binary)
- Not a replacement for Kiro Crew itself
- Not Cursor IDE source — Cursor Agent ACP is closed; this shim translates the live wire

## Docs

- [How the ACP bridge works](docs/HOW-IT-WORKS.md)
- [Install and launch](docs/INSTALL.md)
- [Environment and models](docs/CONFIGURATION.md)
- [Troubleshooting](docs/TROUBLESHOOTING.md) — including why Cancel used to keep talking

## Development

```bash
python -m venv .venv
# Windows: .venv\Scripts\python.exe -m pip install -e ".[dev]"
.venv/bin/python -m pip install -e ".[dev]"
.venv/bin/python -m pytest
```

MIT. See [LICENSE](LICENSE).
