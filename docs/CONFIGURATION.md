# Configuration

All keys are optional once `setup` / `gateway` have run. Values live in `%USERPROFILE%\.kiro\crew\.env` unless noted.

| Variable | Default | Meaning |
|---|---|---|
| `KIROCREW_KIRO_BIN` | `.venv/Scripts/kiro-cli.exe` | ACP child Crew will spawn. **This is the switch.** |
| `CURSOR_CREW_HOME` | discovered from `pyproject.toml` | Repo root if the package is not running from a checkout. |
| `CURSOR_CREW_MODEL` | `cursor-grok-4.6-xhigh` | Full chat model. Must be a suffixed Cursor id. |
| `CURSOR_CREW_LITE_MODEL` | `cursor-grok-4.6-high-fast` | Optimize Prompt / `kirocrew-lite`. Never a bare `cursor-grok-4.6`. |
| `CURSOR_CREW_TRACE` | `1` | ACP journal (`crew→` / `cursor←`) in the log files. |
| `CURSOR_CREW_SKIP_MCP` | `0` | `1` skips injecting `~/.kiro/agents/kirocrew.json` into `session/new`. |
| `CURSOR_CREW_BRIDGE_LOG` | `./bridge.log` | Extra log path. Crew sandbox may block `~/.kiro/crew/logs`. |
| `CURSOR_CREW_CONTEXT_WINDOW` | `256000` | Window advertised to Crew. |
| `CURSOR_AUTH_TOKEN` | (from IDE DB) | Override. Do not commit. |
| `CURSOR_AUTH_DB` | Cursor `state.vscdb` | Override path to the IDE SQLite file. |
| `CURSOR_AGENT_BIN` | auto-detect | `cursor-agent.exe` or a `index.js` (needs `node`). |
| `CURSOR_CREW_NODE` | `node` on PATH | Used when the Agent is launched via `index.js`. |
| `KIROCREW_EXE` | default Installer path | `KiroCrew.exe`. |
| `KIRO_OFFICIAL_BIN` | `%LOCALAPPDATA%\Kiro-Cli\kiro-cli.exe` | Used by `cursor-crew default`. |

## Valid Grok model ids

Cursor rejects a bare `cursor-grok-4.6`. Allowed suffixes:

`low`, `low-fast`, `medium`, `medium-fast`, `high`, `high-fast`, `xhigh`, `xhigh-fast`.

The resolver maps unknown / bare ids to `xhigh` (full) or `high-fast` (lite).

## Logs

Written (first writable wins, then extras):

1. `CURSOR_CREW_BRIDGE_LOG`
2. `%USERPROFILE%\.kiro\crew\logs\cursor-crew-bridge.log`
3. `<repo>/bridge.log`
4. `%TEMP%\cursor-crew-bridge.log`

TRACE lines are short. Auth tokens are redacted in argv dumps.

## Crew files the gateway profile touches

| File | Change |
|---|---|
| `~/.kiro/crew/.env` | `KIROCREW_KIRO_BIN` and `CURSOR_CREW_*` |
| `~/.kiro/crew/config.json` | `agent.provider=acp`, `eager_spawn`, long timeouts, `kirocrew-core` stub |
| `~/.kiro/crew/model_windows.json` | 256k for Extra High aliases |
| `~/.kiro/agents/kirocrew.json` | `model` field only |

`cursor-crew default` restores official `KIROCREW_KIRO_BIN` and removes the Cursor-only env keys. It does not uninstall this repo.
