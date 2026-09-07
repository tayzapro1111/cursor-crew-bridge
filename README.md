# cursor-crew-bridge

Kiro Crew on the left. Cursor’s bill on the right.

Two launchers, one checkout. Pick a backend and Autopilot stays the same cards you already know.

[Русский](README.ru.md) · [简体中文](docs/i18n/README.zh-CN.md) · [日本語](docs/i18n/README.ja.md) · [Español](docs/i18n/README.es.md) · [Deutsch](docs/i18n/README.de.md) · [Português](docs/i18n/README.pt-BR.md) · [Français](docs/i18n/README.fr.md) · [한국어](docs/i18n/README.ko.md)

[Install](docs/INSTALL.md) · [Autopilot](docs/AUTOPILOT.md) · [Internals](docs/HOW-IT-WORKS.md) · [Config](docs/CONFIGURATION.md) · [Fix-it](docs/TROUBLESHOOTING.md) · [Releases](https://github.com/Chumbayoumba/cursor-crew-bridge/releases)

![CI](https://img.shields.io/github/actions/workflow/status/Chumbayoumba/cursor-crew-bridge/ci.yml?branch=main&label=tests)
![Release](https://img.shields.io/github/v/release/Chumbayoumba/cursor-crew-bridge?display_name=tag)
![Python](https://img.shields.io/badge/python-3.11%2B-3776AB)
![License](https://img.shields.io/badge/license-MIT-green)

## Two backends

| Launcher | Who answers | Who you pay | Autopilot |
|---|---|---|---|
| `start-cursor-gateway` | Cursor Agent (Grok Extra High) | Cursor | Crew cards + this package’s plan/stage steers |
| `start-kiro-default` | Official `kiro-cli` | Kiro | Native Kiro (`prompt-orchestrator.md`) |

Flip any time. History lives in Crew’s `conversation_log`, not in a Kiro session file.

## Install

**Windows** — Kiro Crew app, sign into Cursor once, then:

```bat
git clone https://github.com/Chumbayoumba/cursor-crew-bridge.git
cd cursor-crew-bridge
setup.bat
start-cursor-gateway.bat
```

If `doctor` cannot see Cursor Agent CLI, run `setup.ps1`.

**macOS / Linux**

```bash
git clone https://github.com/Chumbayoumba/cursor-crew-bridge.git
cd cursor-crew-bridge
chmod +x setup.sh start-cursor-gateway.sh start-kiro-default.sh
./setup.sh
./start-cursor-gateway.sh
```

Linux: `export KIROCREW_EXE=/path/to/KiroCrew`. Cursor CLI: `curl https://cursor.com/install -fsSL | bash`.

Not affiliated with AWS or Anysphere. You need the Crew desktop app. A Kiro CLI subscription is optional (only the official-Kiro launcher uses it).

## Daily commands

| | Windows | macOS / Linux |
|---|---|---|
| Cursor models | `start-cursor-gateway.bat` | `./start-cursor-gateway.sh` |
| Official Kiro | `start-kiro-default.bat` | `./start-kiro-default.sh` |
| Health | `.venv\Scripts\cursor-crew.exe doctor` | `.venv/bin/cursor-crew doctor` |

```text
cursor-crew setup | doctor | gateway | default | status
```

## Package

```bash
pip install https://github.com/Chumbayoumba/cursor-crew-bridge/releases/latest/download/cursor_crew_bridge-0.4.0-py3-none-any.whl
```

Or `pip install -e ".[dev]"` from a clone. Wheels ship on [GitHub Releases](https://github.com/Chumbayoumba/cursor-crew-bridge/releases).

## What Crew already owns

Chat history, Autopilot cards, MCP, memory, Knowledge. This repo only replaces the child behind `KIROCREW_KIRO_BIN`.

MIT — [LICENSE](LICENSE).
